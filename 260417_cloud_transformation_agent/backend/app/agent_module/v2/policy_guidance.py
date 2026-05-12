"""Per-policy code-generation guidance, stored as a history of entries.

For every Azure Policy (keyed by ``policy_definition_id``) we keep an
append-mostly list of natural-language entries that describe how the
terraform code generator should handle that policy.  Entries have a source
so the UI can distinguish user-written vs AI-drafted vs default-seeded
guidance.

Disk: ``backend/.policy_guidance.json``::

    {
      "schema_version": 2,
      "policies": {
        "<policy_definition_id>": {
          "policy_name": "...",
          "entries": [
            {"id": "uuid", "text": "...", "source": "user"|"ai_draft"|"default",
             "created_at": ..., "updated_at": ...},
            ...
          ]
        }
      }
    }

Defaults: ``_DEFAULT_TEMPLATES`` carries the storage-account cascading rules
the previous prototype kept as a global "general_notes" list.  At policy
discovery time, if a policy matches a template's ``trigger`` and the policy
has zero saved entries, the template is materialised as a ``source="default"``
entry — preserving the original knowledge but now scoped to the specific
policy that triggered it.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_GUIDANCE_FILE = _BACKEND_ROOT / ".policy_guidance.json"

_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────
# Default templates — keyword/property triggers → guidance text
# ──────────────────────────────────────────────────────────────────

_DEFAULT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id":      "default-storage-azuread",
        "trigger": {
            "arm_property_contains": "allowSharedKeyAccess",
            "value":                 False,
        },
        "text": (
            "이 정책으로 storage account 의 allowSharedKeyAccess 가 false 가 되면,"
            " 단순히 리소스 블록에 shared_access_key_enabled = false 만 넣어선"
            " 안 됩니다.  함께 반영해야 할 것:\n"
            "  • providers.tf 의 provider \"azurerm\" 블록에"
            " storage_use_azuread = true 추가 (없으면 terraform 의 storage"
            " data plane 작업이 shared key 로 시도되어 실패).\n"
            "  • azurerm_storage_container 등 data-plane 리소스가 있으면,"
            " storage_account_name 대신 storage_account_id 로 참조 (provider v4+).\n"
            "  • README 에 \"사용자/SP 에 'Storage Blob Data Contributor' RBAC 필요\""
            " 한 줄 안내."
        ),
    },
    {
        "id":      "default-blob-public-access",
        "trigger": {
            "arm_property_contains": "allowBlobPublicAccess",
            "value":                 False,
        },
        "text": (
            "이 정책으로 storage account 의 allowBlobPublicAccess 가 false 가 되면,"
            " 같은 plan 의 모든 azurerm_storage_container 의 container_access_type"
            " 은 \"private\" 으로 강제하세요.  현재 코드에 \"public\" 이나 \"blob\""
            " 값이 있으면 \"private\" 로 교체."
        ),
    },
    {
        "id":      "default-disable-local-auth",
        "trigger": {
            "arm_property_contains": "disableLocalAuth",
            "value":                 True,
        },
        "text": (
            "이 정책으로 disableLocalAuth 가 true 가 되면, 대응하는 terraform"
            " attribute 는 local_auth_enabled = false 입니다 (값 반전).  데이터플레인"
            " 접근은 Azure AD 토큰으로 인증해야 하므로 README 에 \"클라이언트는"
            " Azure AD 토큰으로 인증해야 함\" 한 줄 추가."
        ),
    },
]


# ──────────────────────────────────────────────────────────────────
# Persistence helpers
# ──────────────────────────────────────────────────────────────────

def _empty_store() -> Dict[str, Any]:
    return {"schema_version": 2, "policies": {}, "general_entries": []}


def _read() -> Dict[str, Any]:
    if not _GUIDANCE_FILE.exists():
        return _empty_store()
    try:
        data = json.loads(_GUIDANCE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "policies" not in data:
            return _empty_store()
        return data
    except Exception:
        return _empty_store()


def _write(store: Dict[str, Any]) -> None:
    _GUIDANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _GUIDANCE_FILE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _new_entry(text: str, source: str) -> Dict[str, Any]:
    now = time.time()
    return {
        "id":         str(uuid.uuid4()),
        "text":       (text or "").strip(),
        "source":     source,
        "created_at": now,
        "updated_at": now,
    }


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def load_all() -> Dict[str, Any]:
    with _lock:
        return _read()


def get_entries(policy_definition_id: str) -> List[Dict[str, Any]]:
    if not policy_definition_id:
        return []
    store = load_all()
    return (store.get("policies", {}).get(policy_definition_id, {}) or {}).get("entries", []) or []


def add_entry(
    policy_definition_id: str,
    policy_name: str,
    text: str,
    *,
    source: str = "user",
) -> Dict[str, Any]:
    if not policy_definition_id:
        raise ValueError("policy_definition_id required")
    text = (text or "").strip()
    if not text:
        raise ValueError("entry text must not be empty")
    if source not in ("user", "ai_draft", "default"):
        raise ValueError(f"invalid source: {source}")
    with _lock:
        store = _read()
        policies = store.setdefault("policies", {})
        bucket = policies.setdefault(policy_definition_id, {"policy_name": policy_name or "", "entries": []})
        if policy_name and bucket.get("policy_name") != policy_name:
            bucket["policy_name"] = policy_name
        entry = _new_entry(text, source)
        bucket["entries"].append(entry)
        _write(store)
        return entry


def update_entry(policy_definition_id: str, entry_id: str, text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        raise ValueError("entry text must not be empty")
    with _lock:
        store = _read()
        bucket = (store.get("policies") or {}).get(policy_definition_id)
        if not bucket:
            return None
        for e in bucket.get("entries") or []:
            if e.get("id") == entry_id:
                e["text"] = text
                e["updated_at"] = time.time()
                # If a default was edited, promote to user
                if e.get("source") == "default":
                    e["source"] = "user"
                _write(store)
                return e
        return None


def delete_entry(policy_definition_id: str, entry_id: str) -> bool:
    with _lock:
        store = _read()
        bucket = (store.get("policies") or {}).get(policy_definition_id)
        if not bucket:
            return False
        before = len(bucket.get("entries") or [])
        bucket["entries"] = [e for e in (bucket.get("entries") or []) if e.get("id") != entry_id]
        after = len(bucket["entries"])
        if before == after:
            return False
        _write(store)
        return True


def entries_for_policies(policy_definition_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Return ``{policy_definition_id: [entries...]}`` for the requested ids,
    only those with non-empty entries."""
    store = load_all()
    pol = store.get("policies") or {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for pid in policy_definition_ids:
        if not pid:
            continue
        bucket = pol.get(pid) or {}
        entries = bucket.get("entries") or []
        if entries:
            out[pid] = entries
    return out


# ──────────────────────────────────────────────────────────────────
# Selection — which policies the user has opted into for plan generation
# ──────────────────────────────────────────────────────────────────

def is_selected(policy_definition_id: str) -> bool:
    if not policy_definition_id:
        return False
    bucket = (load_all().get("policies") or {}).get(policy_definition_id) or {}
    return bool(bucket.get("selected"))


def set_selected(policy_definition_id: str, policy_name: str, selected: bool) -> Dict[str, Any]:
    """Toggle a policy's ``selected`` flag.  Creates a bucket if the policy
    was never touched before (so we can remember 'unchecked' too)."""
    if not policy_definition_id:
        raise ValueError("policy_definition_id required")
    with _lock:
        store = _read()
        policies = store.setdefault("policies", {})
        bucket = policies.setdefault(
            policy_definition_id,
            {"policy_name": policy_name or "", "entries": [], "selected": False},
        )
        if policy_name and bucket.get("policy_name") != policy_name:
            bucket["policy_name"] = policy_name
        bucket["selected"] = bool(selected)
        _write(store)
        return {
            "policy_definition_id": policy_definition_id,
            "selected":             bucket["selected"],
            "policy_name":          bucket.get("policy_name") or "",
            "entries":              bucket.get("entries") or [],
        }


def selected_policy_ids() -> List[str]:
    """All policy_definition_ids the user has marked as applying to plan
    generation.  Used by the pipeline to filter policy_constraints."""
    pol = (load_all().get("policies") or {})
    return [pid for pid, b in pol.items() if (b or {}).get("selected")]


# ──────────────────────────────────────────────────────────────────
# General entries — code-generation guidance not tied to any policy
# ──────────────────────────────────────────────────────────────────

def list_general_entries() -> List[Dict[str, Any]]:
    return list((load_all().get("general_entries") or []))


def add_general_entry(text: str, source: str = "user") -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("entry text must not be empty")
    if source not in ("user", "ai_draft", "default"):
        raise ValueError(f"invalid source: {source}")
    with _lock:
        store = _read()
        entries = store.setdefault("general_entries", [])
        entry = _new_entry(text, source)
        entries.append(entry)
        _write(store)
        return entry


def update_general_entry(entry_id: str, text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        raise ValueError("entry text must not be empty")
    with _lock:
        store = _read()
        for e in (store.get("general_entries") or []):
            if e.get("id") == entry_id:
                e["text"] = text
                e["updated_at"] = time.time()
                if e.get("source") == "default":
                    e["source"] = "user"
                _write(store)
                return e
        return None


def delete_general_entry(entry_id: str) -> bool:
    with _lock:
        store = _read()
        before = store.get("general_entries") or []
        after = [e for e in before if e.get("id") != entry_id]
        if len(after) == len(before):
            return False
        store["general_entries"] = after
        _write(store)
        return True


def general_entry_texts() -> List[str]:
    """Plain text list for prompt injection.  Empty strings filtered."""
    return [e.get("text") for e in list_general_entries() if (e.get("text") or "").strip()]


# ──────────────────────────────────────────────────────────────────
# Default-template seeding (runs at discover time)
# ──────────────────────────────────────────────────────────────────

def _modify_op_matches_trigger(op: Dict[str, Any], trigger: Dict[str, Any]) -> bool:
    """Match a policy's modifyOperations entry against a template trigger.

    ``op`` shape is whatever ``extract_modify_operations`` produces — usually
    ``{"field": "properties.allowSharedKeyAccess", "operation": "addOrReplace",
       "value": false}``.  The template trigger uses ``arm_property_contains``
    (substring match on the field name) plus an exact ``value`` match.
    """
    field = (op.get("field") or "").lower()
    needle = (trigger.get("arm_property_contains") or "").lower()
    if needle and needle not in field:
        return False
    if "value" in trigger and op.get("value") != trigger["value"]:
        return False
    return True


def maybe_seed_defaults_for_policy(
    policy_definition_id: str,
    policy_name: str,
    modify_operations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """If this policy has no entries yet and any of its modifyOperations match
    a default template, seed those templates as ``source="default"`` entries.

    Returns the list of newly-seeded entries (may be empty)."""
    if not policy_definition_id:
        return []
    existing = get_entries(policy_definition_id)
    if existing:
        return []   # user already curated — don't overwrite

    matched: List[Dict[str, Any]] = []
    seen_template_ids: set = set()
    for op in modify_operations or []:
        for tmpl in _DEFAULT_TEMPLATES:
            if tmpl["id"] in seen_template_ids:
                continue
            if _modify_op_matches_trigger(op, tmpl["trigger"]):
                try:
                    entry = add_entry(policy_definition_id, policy_name, tmpl["text"], source="default")
                except ValueError:
                    continue
                # Tag with the template id so we can dedupe / show source nicely
                entry["template_id"] = tmpl["id"]
                seen_template_ids.add(tmpl["id"])
                matched.append(entry)
    return matched


# ──────────────────────────────────────────────────────────────────
# Helper for the code-generator: build a prompt-ready context block
# ──────────────────────────────────────────────────────────────────

def build_guidance_payload(policy_definition_ids: List[str]) -> Dict[str, Any]:
    """Build a JSON-safe payload for injection into the codegen LLM prompt.

    Shape::
        {
          "<policy_definition_id>": {
            "policy_name": "...",
            "entries":     ["text1", "text2", ...]  // text only — source elided
          }
        }
    Only includes policies that actually have entries.
    """
    store = load_all()
    pol = store.get("policies") or {}
    out: Dict[str, Any] = {}
    for pid in policy_definition_ids:
        if not pid:
            continue
        bucket = pol.get(pid) or {}
        entries = bucket.get("entries") or []
        texts = [e.get("text") for e in entries if (e.get("text") or "").strip()]
        if not texts:
            continue
        out[pid] = {
            "policy_name": bucket.get("policy_name") or "",
            "entries":     texts,
        }
    return out
