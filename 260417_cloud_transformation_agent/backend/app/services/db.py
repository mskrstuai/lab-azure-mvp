"""Lightweight SQLite persistence layer.

Goal: replace what used to live only in-memory dicts so a backend reload
doesn't lose state.  Schema is intentionally tiny — JSON blobs for nested
shapes, no ORM, no migrations framework.  Single file at
``backend/.cta-state.db`` (configurable via ``CTA_DB_PATH``).

Phase 1 (this PR): add `selected_plans` table only — used by the new
multi-Selected Plan UI.  `deploys` schema is included so a later phase
can migrate `_deploys` without another schema bump.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _BACKEND_ROOT / ".cta-state.db"


def _db_path() -> Path:
    p = os.getenv("CTA_DB_PATH")
    return Path(p) if p else _DEFAULT_PATH


# Single shared connection guarded by a lock — sqlite3 with
# check_same_thread=False + a serializing lock is plenty for our QPS
# (UI clicks, not high-throughput API).
_CONN_LOCK = threading.Lock()
_CONN: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.execute("PRAGMA foreign_keys=ON")
        _init_schema(_CONN)
        logger.info("SQLite state DB at %s", path)
    return _CONN


@contextmanager
def cursor():
    conn = _get_conn()
    with _CONN_LOCK:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


# ── Schema ───────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS selected_plans (
  id            TEXT PRIMARY KEY,
  name          TEXT,
  status        TEXT NOT NULL,           -- 'selected' | 'mapped'
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL,
  source_account TEXT,                   -- aws account id (for display)
  source_region  TEXT,                   -- aws region (for display)
  discovery_mode TEXT,                   -- 'architecture' | 'tag' | 'rg' | ...
  resource_group TEXT,                   -- discovery scope (RG name) when applicable
  azure_region   TEXT,
  goals          TEXT,
  resource_count INTEGER DEFAULT 0,
  scoped_meta   TEXT,                    -- JSON
  scoped_rows   TEXT,                    -- JSON
  architecture  TEXT,                    -- JSON
  mappings      TEXT,                    -- JSON (when mapped)
  plan_run_id   TEXT                     -- run_id (yyyymmdd_HHmmss) of the
                                          -- generated Plan output dir on disk
);
CREATE INDEX IF NOT EXISTS idx_selected_plans_updated ON selected_plans(updated_at DESC);


-- Sanitized session metadata.  Only display-safe info; the live credential
-- objects (boto3 Session, Azure credential) stay in-memory.  After backend
-- reload, rows here let the UI bottom bar still show "what was connected"
-- with a 'stale' badge until the user reconnects.
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL,
  aws_meta      TEXT,                    -- JSON: { account_id, region, method, identity_summary }
  azure_meta    TEXT,                    -- JSON: { subscription_id, subscription_name, region, tenant_id, method }
  scope         TEXT                     -- JSON: resolved Phase-0 scope
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Best-effort additive migrations for older DBs (idempotent — IGNORE if column exists).
    for sql in (
        "ALTER TABLE selected_plans ADD COLUMN discovery_mode TEXT",
        "ALTER TABLE selected_plans ADD COLUMN resource_group TEXT",
        "ALTER TABLE selected_plans ADD COLUMN plan_run_id TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists


def _row_to_selected_plan(r: sqlite3.Row) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: r[k] for k in r.keys()}
    for k in ("scoped_meta", "scoped_rows", "architecture", "mappings"):
        v = out.get(k)
        if isinstance(v, str) and v:
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                out[k] = None
        elif v is None:
            out[k] = None
    return out


# ── Selected plans CRUD ──────────────────────────────────────────

def list_selected_plans() -> List[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute("""
            SELECT id, name, status, created_at, updated_at, source_account, source_region,
                   discovery_mode, resource_group, azure_region, goals, resource_count,
                   plan_run_id
            FROM selected_plans
            ORDER BY updated_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_selected_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute("SELECT * FROM selected_plans WHERE id = ?", (plan_id,))
        r = cur.fetchone()
        return _row_to_selected_plan(r) if r else None


def create_selected_plan(*,
                         name: Optional[str],
                         scoped_meta: Optional[Dict[str, Any]],
                         scoped_rows: Optional[List[Dict[str, Any]]],
                         architecture: Optional[Dict[str, Any]] = None,
                         mappings: Optional[List[Dict[str, Any]]] = None,
                         azure_region: Optional[str] = None,
                         goals: Optional[str] = None) -> Dict[str, Any]:
    plan_id = str(uuid.uuid4())
    now = time.time()
    rows = scoped_rows or []
    meta = scoped_meta or {}
    status = "mapped" if (mappings and len(mappings) > 0) else "selected"
    # Pull display-friendly fields out of meta for fast list queries
    discovery_mode = meta.get("mode")
    resource_group = meta.get("resourceGroup") or meta.get("resource_group")
    # AWS account: meta first, then architecture as fallback
    src_account = meta.get("account_id") or (architecture or {}).get("account_id")
    src_region  = meta.get("region")     or (architecture or {}).get("region")
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO selected_plans
              (id, name, status, created_at, updated_at, source_account, source_region,
               discovery_mode, resource_group, azure_region, goals, resource_count,
               scoped_meta, scoped_rows, architecture, mappings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id, name, status, now, now,
                src_account, src_region,
                discovery_mode, resource_group,
                azure_region, goals, len(rows),
                json.dumps(meta, ensure_ascii=False),
                json.dumps(rows, ensure_ascii=False, default=str),
                json.dumps(architecture or {}, ensure_ascii=False, default=str) if architecture else None,
                json.dumps(mappings, ensure_ascii=False, default=str) if mappings else None,
            ),
        )
    return get_selected_plan(plan_id)


# Status lattice — writes must move forward (or stay) on this ordering.
# "selected" → "mapping" → "mapped" → "planning" → "ready"
# This stops a stale frontend useEffect (e.g. mapping.phase=complete after
# Plan 수립 was already kicked off) from regressing status="planning" back
# to "mapped".
_STATUS_ORDER = {
    "selected": 0,
    "mapping":  1,
    "mapped":   2,
    "planning": 3,
    "ready":    4,
}


def update_selected_plan(plan_id: str, *,
                         name: Optional[str] = None,
                         status: Optional[str] = None,
                         azure_region: Optional[str] = None,
                         goals: Optional[str] = None,
                         architecture: Optional[Dict[str, Any]] = None,
                         mappings: Optional[List[Dict[str, Any]]] = None,
                         plan_run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    # Drop status-regression silently rather than 500'ing — many writes are
    # "best effort" PATCHes from the frontend.
    if status is not None:
        cur_row = get_selected_plan(plan_id)
        if cur_row:
            cur_order = _STATUS_ORDER.get(cur_row.get("status") or "", -1)
            new_order = _STATUS_ORDER.get(status, -1)
            if new_order >= 0 and new_order < cur_order:
                status = None  # ignore regressive write

    fields: List[str] = []
    params: List[Any] = []
    if name is not None:
        fields.append("name = ?"); params.append(name)
    if status is not None:
        fields.append("status = ?"); params.append(status)
    if azure_region is not None:
        fields.append("azure_region = ?"); params.append(azure_region)
    if goals is not None:
        fields.append("goals = ?"); params.append(goals)
    if architecture is not None:
        fields.append("architecture = ?"); params.append(json.dumps(architecture, ensure_ascii=False, default=str))
    if mappings is not None:
        fields.append("mappings = ?"); params.append(json.dumps(mappings, ensure_ascii=False, default=str))
        # Auto-promote status when mappings get filled — but only forward
        if status is None and mappings:
            cur_row = get_selected_plan(plan_id)
            cur_order = _STATUS_ORDER.get((cur_row or {}).get("status") or "", -1)
            mapped_order = _STATUS_ORDER["mapped"]
            if mapped_order >= cur_order:
                fields.append("status = ?"); params.append("mapped")
    if plan_run_id is not None:
        fields.append("plan_run_id = ?"); params.append(plan_run_id)
    if not fields:
        return get_selected_plan(plan_id)
    fields.append("updated_at = ?"); params.append(time.time())
    params.append(plan_id)
    with cursor() as cur:
        cur.execute(f"UPDATE selected_plans SET {', '.join(fields)} WHERE id = ?", params)
    return get_selected_plan(plan_id)


def delete_selected_plan(plan_id: str) -> bool:
    with cursor() as cur:
        cur.execute("DELETE FROM selected_plans WHERE id = ?", (plan_id,))
        return cur.rowcount > 0


def delete_selected_plans(plan_ids: Iterable[str]) -> int:
    ids = list(plan_ids)
    if not ids:
        return 0
    placeholders = ", ".join("?" * len(ids))
    with cursor() as cur:
        cur.execute(f"DELETE FROM selected_plans WHERE id IN ({placeholders})", ids)
        return cur.rowcount or 0


# ── Sessions (sanitized metadata only) ───────────────────────────

def _row_to_session(r: sqlite3.Row) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: r[k] for k in r.keys()}
    for k in ("aws_meta", "azure_meta", "scope"):
        v = out.get(k)
        if isinstance(v, str) and v:
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                out[k] = None
        elif v is None:
            out[k] = None
    return out


def list_sessions() -> List[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        return [_row_to_session(r) for r in cur.fetchall()]


def get_session_meta(session_id: str) -> Optional[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        r = cur.fetchone()
        return _row_to_session(r) if r else None


def upsert_session(session_id: str, *,
                   aws_meta: Optional[Dict[str, Any]] = None,
                   azure_meta: Optional[Dict[str, Any]] = None,
                   scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Insert or update a session row.  Only fields explicitly passed are
    overwritten — pass None to leave existing value alone, ``{}`` to clear."""
    now = time.time()
    existing = get_session_meta(session_id)
    if existing is None:
        with cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (id, created_at, updated_at, aws_meta, azure_meta, scope) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id, now, now,
                    json.dumps(aws_meta, ensure_ascii=False, default=str) if aws_meta is not None else None,
                    json.dumps(azure_meta, ensure_ascii=False, default=str) if azure_meta is not None else None,
                    json.dumps(scope, ensure_ascii=False, default=str) if scope is not None else None,
                ),
            )
        return get_session_meta(session_id)

    fields: List[str] = []
    params: List[Any] = []
    if aws_meta is not None:
        fields.append("aws_meta = ?")
        params.append(json.dumps(aws_meta, ensure_ascii=False, default=str))
    if azure_meta is not None:
        fields.append("azure_meta = ?")
        params.append(json.dumps(azure_meta, ensure_ascii=False, default=str))
    if scope is not None:
        fields.append("scope = ?")
        params.append(json.dumps(scope, ensure_ascii=False, default=str))
    if not fields:
        return existing
    fields.append("updated_at = ?")
    params.append(now)
    params.append(session_id)
    with cursor() as cur:
        cur.execute(f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", params)
    return get_session_meta(session_id)


def delete_session(session_id: str) -> bool:
    with cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0
