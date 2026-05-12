"""REST API for per-policy code-generation guidance.

  GET    /policy-guidance                                    — full snapshot
  GET    /policy-guidance/{policy_definition_id:path}        — one policy's entries
  POST   /policy-guidance/{policy_definition_id:path}/entries
         body: {text, source?, policy_name?}                  — append a new entry
  PUT    /policy-guidance/{policy_definition_id:path}/entries/{entry_id}
         body: {text}                                          — edit existing
  DELETE /policy-guidance/{policy_definition_id:path}/entries/{entry_id}
                                                              — remove
  POST   /policy-guidance/{policy_definition_id:path}/draft
         body: {raw_policy, scope_resource_types?}             — AI draft (no persist)

The companion ``/policy-review/discover`` endpoint (in this same router) is
the gate the UI uses between mapping and Plan 수립: it returns the policies
relevant to the user's current Azure mapping, enriched with each policy's
guidance entries (and auto-seeded defaults for first-time policies).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from app.agent_module.v2 import policy_guidance as svc


router = APIRouter(prefix="/policy-guidance", tags=["policy-guidance"])
review_router = APIRouter(prefix="/policy-review", tags=["policy-review"])

# All POST/PUT/DELETE endpoints take ``policy_definition_id`` in the request
# body (or query) rather than in the URL path.  ARM policy ids contain forward
# slashes (e.g. ``/subscriptions/.../policySetDefinitions/SFI-...``) which
# would collide with ``:path`` routing when stacked next to literal suffixes
# like ``/entries`` or ``/draft`` (FastAPI matched the wrong pattern and the
# user saw a "Method Not Allowed").  Putting the id in the body sidesteps all
# URL-encoding headaches and is unambiguous.


def _require_pid(body: Dict[str, Any]) -> str:
    pid = (body.get("policy_definition_id") or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="policy_definition_id required in body")
    return pid


# ──────────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────────

@router.get("")
def get_all_guidance():
    return svc.load_all()


@router.get("/entries")
def get_policy_entries(policy_definition_id: str):
    """GET /policy-guidance/entries?policy_definition_id=..."""
    entries = svc.get_entries(policy_definition_id)
    return {"policy_definition_id": policy_definition_id, "entries": entries}


# ──────────────────────────────────────────────────────────────────
# Write
# ──────────────────────────────────────────────────────────────────

@router.post("/entries")
def post_entry(body: Dict[str, Any] = Body(...)):
    pid  = _require_pid(body)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text must be a non-empty string")
    source = body.get("source") or "user"
    if source not in ("user", "ai_draft", "default"):
        raise HTTPException(status_code=400, detail=f"invalid source: {source}")
    policy_name = (body.get("policy_name") or "").strip()
    try:
        entry = svc.add_entry(pid, policy_name, text, source=source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"policy_definition_id": pid, "entry": entry}


@router.put("/entries/{entry_id}")
def put_entry(entry_id: str, body: Dict[str, Any] = Body(...)):
    pid  = _require_pid(body)
    text = body.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string")
    try:
        updated = svc.update_entry(pid, entry_id, text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"policy_definition_id": pid, "entry": updated}


@router.delete("/entries/{entry_id}")
def remove_entry(entry_id: str, policy_definition_id: str):
    """DELETE /policy-guidance/entries/{entry_id}?policy_definition_id=..."""
    ok = svc.delete_entry(policy_definition_id, entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"deleted": True}


# ──────────────────────────────────────────────────────────────────
# AI draft — returns a single suggested entry, does NOT persist
# ──────────────────────────────────────────────────────────────────

@router.post("/draft")
def draft_entry(body: Dict[str, Any] = Body(...)):
    policy_definition_id = _require_pid(body)
    raw_policy = body.get("raw_policy") or {}
    if not isinstance(raw_policy, dict) or not raw_policy:
        raise HTTPException(status_code=400, detail="raw_policy (dict) is required")
    scope_types = body.get("scope_resource_types") or []
    if not isinstance(scope_types, list):
        raise HTTPException(status_code=400, detail="scope_resource_types must be a list")

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    if not endpoint:
        raise HTTPException(status_code=503, detail="AZURE_OPENAI_ENDPOINT not configured")

    from app.agent_module.v2.strategy import _build_client

    sys_prompt = """\
당신은 Azure Policy → Terraform 매핑 가이드를 작성하는 전문가입니다.

입력으로 받은 raw Azure Policy JSON 을 보고, terraform 코드 생성기에 줘야 할
지침(guidance) 을 협업 노트 톤의 한국어 산문으로 작성합니다.  길이는 3~6문장
또는 한두 단락.

지침에 포함하면 좋은 것 (해당되는 경우만):
  • 이 정책의 ARM property → azurerm provider attribute 매핑 (예시 포함)
  • 영향받는 terraform 리소스 타입
  • 함께 변경해야 할 cascading 효과 (provider 블록, 연관 데이터플레인 리소스,
    README 안내 등)
  • 값 변환 규칙 (boolean 반전, enum → boolean 등)
  • 예외 / 적용 제외 조건

규칙:
  • 출력은 메모 본문 텍스트만.  헤더, 코드 펜스, 마크다운 ## 같은거 쓰지 말 것.
  • 모르는 부분은 추측해서 적지 말고 생략.
  • 메타 설명 (\"이 메모는…\") 금지.
"""

    user_parts: List[str] = [
        "## 원본 Azure Policy JSON",
        "```json",
        json.dumps(raw_policy, ensure_ascii=False, default=str, indent=2),
        "```",
    ]
    if scope_types:
        user_parts.append("")
        user_parts.append(f"## 현재 plan 의 azurerm 리소스 타입 ({len(scope_types)}개)")
        user_parts.append(json.dumps(scope_types, ensure_ascii=False))
    # Surface any existing entries for this policy so AI doesn't repeat them
    existing = svc.get_entries(policy_definition_id)
    if existing:
        user_parts.append("")
        user_parts.append(f"## 이미 작성된 지침 ({len(existing)}건) — 중복 회피")
        for i, e in enumerate(existing, 1):
            user_parts.append(f"{i}. {e.get('text', '')}")
    user_parts.append("")
    user_parts.append("위 정책에 대해 새 지침 한 건을 작성하세요.")
    user_prompt = "\n".join(user_parts)

    client = _build_client(deployment, endpoint)
    try:
        completion = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {e}")

    msg = completion.choices[0].message
    draft = (msg.content or "").strip()
    if not draft:
        raise HTTPException(status_code=502, detail="LLM 이 빈 응답을 반환했습니다")
    return {"policy_definition_id": policy_definition_id, "draft": draft, "model": deployment}


# ──────────────────────────────────────────────────────────────────
# Discover relevant policies (gate before Plan 수립)
# ──────────────────────────────────────────────────────────────────

@review_router.post("/discover")
def discover_relevant_policies(body: Dict[str, Any] = Body(...)):
    """Return ALL enforced policies (MODIFY + DENY) for the target sub.

    The user picks which ones apply to the plan via the ``selected`` flag —
    no automatic type-based filtering.  Each policy carries its current
    guidance entries and selection state.

    Body: ``{subscription_id}``  (azure_types is accepted for backward compat
    but no longer used as a filter.)

    Response::

        {
          policies: [{policy_definition_id, policy_name, effect, azure_type,
                      raw, entries: [...], selected: bool}],
          summary:  {total, modify, deny, selected, selected_with_entries,
                     selected_without_entries, seeded}
        }
    """
    sub_id = (body.get("subscription_id") or "").strip()
    if not sub_id:
        raise HTTPException(status_code=400, detail="subscription_id is required")

    from app.services.azure_policy import extract_constraints

    try:
        pc = extract_constraints(sub_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"정책 조회 실패: {e}")

    field_ops  = pc.get("field_operations") or []
    deny_rules = pc.get("manual_review")    or []

    out: List[Dict[str, Any]] = []
    seen: set = set()
    total_seeded = 0

    for op in field_ops:
        pid = op.get("policy_definition_id") or ""
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        policy_name = op.get("policy_name") or "(이름 없음)"
        seeded = svc.maybe_seed_defaults_for_policy(pid, policy_name, op.get("operations") or [])
        total_seeded += len(seeded)
        entries = svc.get_entries(pid)
        out.append({
            "policy_definition_id": pid,
            "policy_name":          policy_name,
            "effect":               "MODIFY",
            "azure_type":           op.get("azure_type"),
            "raw":                  op,
            "entries":              entries,
            "selected":             svc.is_selected(pid),
        })

    for d in deny_rules:
        pid = d.get("policy_definition_id") or ""
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        policy_name = d.get("name") or "(이름 없음)"
        entries = svc.get_entries(pid)
        out.append({
            "policy_definition_id": pid,
            "policy_name":          policy_name,
            "effect":               "DENY",
            "azure_type":           d.get("resourceType"),
            "raw":                  d,
            "entries":              entries,
            "selected":             svc.is_selected(pid),
        })

    # Stable sort: selected first, then effect (MODIFY before DENY), then name
    out.sort(key=lambda x: (
        0 if x["selected"] else 1,
        0 if x["effect"] == "MODIFY" else 1,
        (x.get("policy_name") or "").lower(),
    ))

    selected_count = sum(1 for x in out if x["selected"])
    summary = {
        "total":                    len(out),
        "modify":                   sum(1 for x in out if x["effect"] == "MODIFY"),
        "deny":                     sum(1 for x in out if x["effect"] == "DENY"),
        "selected":                 selected_count,
        "selected_with_entries":    sum(1 for x in out if x["selected"] and x["entries"]),
        "selected_without_entries": sum(1 for x in out if x["selected"] and not x["entries"]),
        "seeded":                   total_seeded,
    }
    return {
        "subscription_id": sub_id,
        "policies":        out,
        "summary":         summary,
    }


# ──────────────────────────────────────────────────────────────────
# Toggle a policy's selected flag
# ──────────────────────────────────────────────────────────────────

@router.put("/selected")
def put_selected(body: Dict[str, Any] = Body(...)):
    pid = _require_pid(body)
    selected = body.get("selected")
    if not isinstance(selected, bool):
        raise HTTPException(status_code=400, detail="selected must be boolean")
    policy_name = (body.get("policy_name") or "").strip()
    try:
        result = svc.set_selected(pid, policy_name, selected)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ──────────────────────────────────────────────────────────────────
# General guidance entries — injected into every codegen call
# ──────────────────────────────────────────────────────────────────

@router.get("/general-entries")
def list_general():
    return {"entries": svc.list_general_entries()}


@router.post("/general-entries")
def add_general(body: Dict[str, Any] = Body(...)):
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text must be a non-empty string")
    try:
        entry = svc.add_general_entry(text, source=body.get("source") or "user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"entry": entry}


@router.put("/general-entries/{entry_id}")
def update_general(entry_id: str, body: Dict[str, Any] = Body(...)):
    text = body.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string")
    try:
        entry = svc.update_general_entry(entry_id, text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not entry:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"entry": entry}


@router.delete("/general-entries/{entry_id}")
def delete_general(entry_id: str):
    ok = svc.delete_general_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"deleted": True}
