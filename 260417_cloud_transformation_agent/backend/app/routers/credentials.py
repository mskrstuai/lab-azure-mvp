"""Phase 0: Credential & Account session management.

Sessions are in-memory only — credentials never touch disk or the wire
(the frontend receives identity info, never raw keys/tokens).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import aws_auth, azure_auth
from app.services import db as state_db

router = APIRouter(prefix="/credentials", tags=["credentials"])

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------
_sessions: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_SESSION_TTL = 7200  # 2 hours


def _new_session_id() -> str:
    sid = str(uuid.uuid4())
    with _lock:
        _sessions[sid] = {
            "created_at": time.time(),
            "aws": None,   # { session, identity, region, method, org_accounts, assumed_sessions }
            "azure": None, # { credential, subscriptions, method, tenant_id }
            "scope": None, # { aws_account_id, aws_region, azure_subscription_id, azure_subscription_name, azure_region }
        }
    return sid


def _get(session_id: str) -> Dict[str, Any]:
    with _lock:
        s = _sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if time.time() - s["created_at"] > _SESSION_TTL:
        with _lock:
            _sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Session expired — please reconnect")
    return s


def _safe_aws(aws: Optional[Dict]) -> Optional[Dict]:
    if not aws:
        return None
    return {
        "connected": True,
        "identity": aws["identity"],
        "region": aws["region"],
        "method": aws["method"],
        "org_accounts": aws.get("org_accounts", []),
        "has_org": len(aws.get("org_accounts", [])) > 1,
        "assumed_accounts": list(aws.get("assumed_sessions", {}).keys()),
    }


def _safe_azure(azure: Optional[Dict]) -> Optional[Dict]:
    if not azure:
        return None
    return {
        "connected": True,
        "method": azure["method"],
        "tenant_id": azure.get("tenant_id"),
        "subscriptions": azure["subscriptions"],
    }


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AwsConnectRequest(BaseModel):
    method: str = Field(description="profile | static_keys | default")
    profile: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    region: str = "us-east-1"
    session_id: Optional[str] = None  # pass to reuse existing session


class AssumeRoleRequest(BaseModel):
    session_id: str
    account_id: str
    role_name: str = "MigrationReadRole"


class AzureConnectRequest(BaseModel):
    method: str = Field(description="cli | service_principal")
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    session_id: Optional[str] = None


class ScopeRequest(BaseModel):
    session_id: str
    aws_account_id: str
    aws_region: str
    azure_subscription_id: str
    azure_subscription_name: str
    azure_region: str


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

@router.post("/aws/connect")
def aws_connect(req: AwsConnectRequest):
    """Verify AWS credentials, probe permissions, list Org accounts."""
    try:
        session = aws_auth.build_session(
            method=req.method,
            region=req.region,
            profile=req.profile,
            access_key_id=req.access_key_id,
            secret_access_key=req.secret_access_key,
            session_token=req.session_token,
        )
        identity = aws_auth.verify_identity(session)
    except NoCredentialsError:
        raise HTTPException(
            status_code=401,
            detail="No AWS credentials found. Set AWS_PROFILE, access keys, or run on an EC2 instance with an IAM role.",
        )
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=401, detail=str(e))

    permissions = aws_auth.probe_permissions(session, req.region)
    org_accounts, org_error = aws_auth.list_org_accounts(session)

    # Single-account: synthesise a one-element list from the caller identity
    if not org_accounts:
        org_accounts = [{
            "account_id": identity["account_id"],
            "name": "Current account",
            "email": "",
            "status": "ACTIVE",
        }]

    sid = req.session_id or _new_session_id()
    with _lock:
        if sid not in _sessions:
            _sessions[sid] = {"created_at": time.time(), "aws": None, "azure": None, "scope": None}
        _sessions[sid]["aws"] = {
            "session": session,
            "identity": identity,
            "region": req.region,
            "method": req.method,
            "org_accounts": org_accounts,
            "assumed_sessions": {},
        }

    # Persist sanitized AWS metadata so the bottom-bar can show the
    # connection even after backend reload (live boto3 session is gone but
    # we know what *was* connected).
    try:
        state_db.upsert_session(sid, aws_meta={
            "account_id":  identity.get("account_id"),
            "region":      req.region,
            "method":      req.method,
            "user_arn":    identity.get("arn"),
            "user_id":     identity.get("user_id"),
        })
    except Exception:
        pass  # DB is best-effort; never block the connect flow

    return {
        "session_id": sid,
        "identity": identity,
        "region": req.region,
        "permissions": permissions,
        "permissions_ok": all(p["ok"] for p in permissions),
        "org_accounts": org_accounts,
        "org_error": org_error,
    }


@router.post("/aws/assume-role")
def aws_assume_role(req: AssumeRoleRequest):
    """Assume a cross-account IAM role and add that session to the store."""
    s = _get(req.session_id)
    if not s.get("aws"):
        raise HTTPException(status_code=400, detail="AWS not connected in this session")

    role_arn = f"arn:aws:iam::{req.account_id}:role/{req.role_name}"
    try:
        assumed = aws_auth.assume_role(s["aws"]["session"], role_arn)
        identity = aws_auth.verify_identity(assumed)
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    with _lock:
        _sessions[req.session_id]["aws"]["assumed_sessions"][req.account_id] = assumed

    return {"ok": True, "identity": identity, "role_arn": role_arn}


# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------

@router.post("/azure/connect")
def azure_connect(req: AzureConnectRequest):
    """Verify Azure credentials and list accessible subscriptions."""
    try:
        credential = azure_auth.build_credential(
            method=req.method,
            tenant_id=req.tenant_id,
            client_id=req.client_id,
            client_secret=req.client_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    subscriptions, error = azure_auth.list_subscriptions(credential)
    if error and not subscriptions:
        raise HTTPException(status_code=401, detail=error)

    sid = req.session_id or _new_session_id()
    with _lock:
        if sid not in _sessions:
            _sessions[sid] = {"created_at": time.time(), "aws": None, "azure": None, "scope": None}
        _sessions[sid]["azure"] = {
            "credential": credential,
            "subscriptions": subscriptions,
            "method": req.method,
            "tenant_id": req.tenant_id,
        }

    try:
        state_db.upsert_session(sid, azure_meta={
            "method":          req.method,
            "tenant_id":       req.tenant_id,
            "subscriptions":   subscriptions,
        })
    except Exception:
        pass

    return {
        "session_id": sid,
        "subscriptions": subscriptions,
        "tenant_id": req.tenant_id,
    }


@router.post("/azure/verify-subscription")
def azure_verify_subscription(body: dict):
    """Probe read access on the selected subscription."""
    sid = body.get("session_id", "")
    sub_id = body.get("subscription_id", "")
    s = _get(sid)
    if not s.get("azure"):
        raise HTTPException(status_code=400, detail="Azure not connected")
    result = azure_auth.verify_subscription(s["azure"]["credential"], sub_id)
    return result


# ---------------------------------------------------------------------------
# Scope confirmation
# ---------------------------------------------------------------------------

@router.post("/scope")
def set_scope(req: ScopeRequest):
    """Lock in the migration scope: source account/region → target subscription/region."""
    s = _get(req.session_id)
    if not s.get("aws"):
        raise HTTPException(status_code=400, detail="Connect AWS first")
    if not s.get("azure"):
        raise HTTPException(status_code=400, detail="Connect Azure first")

    scope = {
        "aws_account_id": req.aws_account_id,
        "aws_region": req.aws_region,
        "azure_subscription_id": req.azure_subscription_id,
        "azure_subscription_name": req.azure_subscription_name,
        "azure_region": req.azure_region,
    }
    with _lock:
        _sessions[req.session_id]["scope"] = scope

    try:
        state_db.upsert_session(req.session_id, scope=scope)
    except Exception:
        pass

    return {"ok": True, "scope": scope}


# ---------------------------------------------------------------------------
# Session read / delete
# ---------------------------------------------------------------------------

@router.get("/session/{session_id}")
def get_session(session_id: str):
    """Safe session snapshot — no raw credentials returned."""
    s = _get(session_id)
    return {
        "session_id": session_id,
        "aws": _safe_aws(s.get("aws")),
        "azure": _safe_azure(s.get("azure")),
        "scope": s.get("scope"),
        "ready": bool(s.get("aws") and s.get("azure") and s.get("scope")),
        "expires_in": max(0, int(_SESSION_TTL - (time.time() - s["created_at"]))),
    }


@router.delete("/session/{session_id}")
def delete_session(session_id: str):
    with _lock:
        _sessions.pop(session_id, None)
    try:
        state_db.delete_session(session_id)
    except Exception:
        pass
    return {"ok": True}


@router.get("/active-sessions")
def list_active_sessions():
    """All known sessions (persisted metadata) with a `live` flag.

    The bottom-bar UI uses this so it can show a connection summary even
    after a backend reload — `live: false` means the saved metadata is
    visible but the in-memory credential is gone (user must reconnect to
    actually call AWS/Azure APIs)."""
    out = []
    try:
        rows = state_db.list_sessions()
    except Exception:
        rows = []
    with _lock:
        live_ids = set(_sessions.keys())
    for r in rows:
        sid = r.get("id")
        live_session = _sessions.get(sid) if sid in live_ids else None
        out.append({
            "session_id": sid,
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "aws_meta":   r.get("aws_meta"),
            "azure_meta": r.get("azure_meta"),
            "scope":      r.get("scope"),
            "aws_live":   bool(live_session and live_session.get("aws")),
            "azure_live": bool(live_session and live_session.get("azure")),
            "live":       sid in live_ids,
        })
    return {"sessions": out}
