"""Phase 1: Architecture scan endpoint.

Uses the Phase-0 session (AWS boto3 session) to collect a full
relationship graph — VPC topology, EC2/RDS/ELB/Lambda dependencies.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from typing import List, Optional

from app.routers.credentials import _get
from app.services import aws_architecture

router = APIRouter(prefix="/architecture", tags=["architecture"])


def _get_aws_session(session_id: str):
    """Retrieve the boto3 Session stored in Phase-0 credentials."""
    s = _get(session_id)
    aws = s.get("aws")
    if not aws:
        raise HTTPException(status_code=400, detail="AWS not connected. Complete the Connect step first.")
    # If the target account differs from the caller (cross-account assume-role),
    # use the assumed session; otherwise fall back to the base session.
    scope = s.get("scope") or {}
    target_account = scope.get("aws_account_id")
    assumed = (aws.get("assumed_sessions") or {}).get(target_account)
    return assumed if assumed else aws["session"]


def _get_region(session_id: str) -> str:
    s = _get(session_id)
    scope = s.get("scope") or {}
    aws = s.get("aws") or {}
    return scope.get("aws_region") or aws.get("region") or "us-east-1"


@router.post("/scan")
def scan_architecture(body: dict):
    """Scan AWS architecture using Phase-0 session credentials.

    Body:
        {
          "session_id": "...",
          "region": "ap-northeast-2",        // optional, falls back to scope
          "resource_group": "my-rg",         // optional
          "tag_filters": [                   // optional
            {"key": "Project", "values": ["myapp"]}
          ]
        }
    """
    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    boto_session = _get_aws_session(session_id)
    region = (body.get("region") or "").strip() or _get_region(session_id)
    resource_group = (body.get("resource_group") or "").strip() or None
    tag_filters: Optional[List[dict]] = body.get("tag_filters") or None

    try:
        result = aws_architecture.scan(
            boto_session, region,
            resource_group=resource_group,
            tag_filters=tag_filters,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Architecture scan failed: {e}")

    return result


@router.get("/resource-groups")
def list_resource_groups(session_id: str, region: Optional[str] = None):
    """List AWS Resource Groups available in the session's region."""
    boto_session = _get_aws_session(session_id)
    effective_region = (region or "").strip() or _get_region(session_id)
    try:
        groups = aws_architecture.list_resource_groups(boto_session, effective_region)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"region": effective_region, "groups": groups}


@router.get("/tag-keys")
def list_tag_keys(session_id: str, region: Optional[str] = None):
    """List tag keys used in the account (via Resource Groups Tagging API)."""
    boto_session = _get_aws_session(session_id)
    effective_region = (region or "").strip() or _get_region(session_id)
    try:
        keys = aws_architecture.list_tag_keys(boto_session, effective_region)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"region": effective_region, "tag_keys": keys}


@router.get("/session/{session_id}/scope")
def get_scope(session_id: str):
    """Return the confirmed migration scope for this session."""
    s = _get(session_id)
    scope = s.get("scope")
    if not scope:
        raise HTTPException(status_code=400, detail="Scope not set. Complete the Connect step first.")
    return scope
