"""Scope feasibility check — preflight for Azure deploys.

Combines policy + SKU + quota checks against the planned terraform resources
so the user can see "이 sub × 이 region 에서 이 plan 이 통과될까?" before
clicking apply.

This complements the existing Phase-3 preflight (which only verifies
credentials + work directory).  Returns a structured report the UI renders
inside the start modal.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────

def _run_az(args: List[str], timeout: int = 60) -> Dict[str, Any]:
    """Invoke az CLI and return parsed JSON or raw text + exit info."""
    cmd = ["az"] + args + ["-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"_error": "timeout", "_cmd": " ".join(cmd)}
    except FileNotFoundError:
        return {"_error": "az binary not found on host"}
    if proc.returncode != 0:
        return {"_error": f"exit {proc.returncode}: {(proc.stderr or '').strip()[-400:]}", "_cmd": " ".join(cmd)}
    out = proc.stdout or ""
    try:
        return {"_ok": True, "data": json.loads(out)}
    except json.JSONDecodeError:
        return {"_ok": True, "data": out}


def _read_tf_files(work: Path) -> Dict[str, str]:
    files = {}
    for p in work.rglob("*.tf"):
        rel = p.relative_to(work)
        if rel.parts and rel.parts[0] == ".terraform":
            continue
        try:
            files[str(rel)] = p.read_text(encoding="utf-8")
        except Exception:
            pass
    return files


# ── tf parsing (regex-based — good enough for SKU/region detection) ──

_RES_RE      = re.compile(r'resource\s+"([a-z_]+)"\s+"([a-zA-Z0-9_-]+)"\s*{', re.MULTILINE)
_SIZE_RE     = re.compile(r'\bsize\s*=\s*"([^"]+)"')
_LOCATION_RE = re.compile(r'\blocation\s*=\s*"([^"]+)"')
_SKU_RE      = re.compile(r'\bsku\s*=\s*"([^"]+)"')
_TIER_RE     = re.compile(r'\b(account_tier|tier)\s*=\s*"([^"]+)"')


def _extract_resources(files: Dict[str, str]) -> List[Dict[str, Any]]:
    """Crude HCL scan — pull out resource type/name + any size/location strings.

    Doesn't need full parsing accuracy — even partial info lets us flag the
    common policy/SKU/quota issues.
    """
    out: List[Dict[str, Any]] = []
    for fname, content in files.items():
        for m in _RES_RE.finditer(content):
            res_type, res_name = m.group(1), m.group(2)
            # Pull the resource block body (rough — until matching brace)
            start = m.end()
            depth = 1
            i = start
            while i < len(content) and depth > 0:
                ch = content[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                i += 1
            body = content[start:i]
            entry: Dict[str, Any] = {
                "file": fname,
                "type": res_type,
                "name": res_name,
                "size": None,
                "sku":  None,
                "tier": None,
                "location_literal": None,
            }
            sm = _SIZE_RE.search(body)
            if sm: entry["size"] = sm.group(1)
            lm = _LOCATION_RE.search(body)
            if lm: entry["location_literal"] = lm.group(1)
            skm = _SKU_RE.search(body)
            if skm: entry["sku"] = skm.group(1)
            tm = _TIER_RE.search(body)
            if tm: entry["tier"] = tm.group(2)
            out.append(entry)
    return out


# ── main ────────────────────────────────────────────────────────

def check_scope(
    *,
    work_dir: Path,
    subscription_id: str,
    region: str,
) -> Dict[str, Any]:
    """Run policy + SKU + quota checks against the planned resources.

    Returns a JSON-serializable dict suitable for the API response.
    """
    files = _read_tf_files(work_dir)
    resources = _extract_resources(files)

    vm_resources      = [r for r in resources if r["type"].startswith("azurerm_") and "virtual_machine" in r["type"]]
    storage_resources = [r for r in resources if r["type"] == "azurerm_storage_account"]

    vm_sizes_wanted = sorted({r["size"] for r in vm_resources if r["size"]})

    # ── 1. Policy assignments at subscription scope
    pol_scope = f"/subscriptions/{subscription_id}"
    pol_resp = _run_az([
        "policy", "assignment", "list", "--scope", pol_scope, "--disable-scope-strict-match",
    ])
    policies: List[Dict[str, Any]] = []
    if pol_resp.get("_ok"):
        raw = pol_resp.get("data") or []
        for a in raw:
            policies.append({
                "name":          a.get("name"),
                "display_name":  a.get("displayName") or a.get("display_name"),
                "scope":         a.get("scope"),
                "policy_id":     a.get("policyDefinitionId"),
                "enforcement":   a.get("enforcementMode"),
                "parameters":    a.get("parameters") or {},
            })

    # ── 2. VM SKU availability + restrictions in target region
    vm_sku_resp = _run_az([
        "vm", "list-skus", "--location", region, "--resource-type", "virtualMachines",
    ])
    vm_skus_in_region: Dict[str, Dict[str, Any]] = {}
    if vm_sku_resp.get("_ok"):
        for entry in vm_sku_resp.get("data") or []:
            name = entry.get("name")
            if not name:
                continue
            restrictions = entry.get("restrictions") or []
            blocked = []
            for r in restrictions:
                rt = r.get("type")    # NotAvailableForSubscription | Location
                reason = r.get("reasonCode")
                if rt or reason:
                    blocked.append({"type": rt, "reason": reason})
            vm_skus_in_region[name] = {
                "family":       entry.get("family"),
                "tier":         entry.get("tier"),
                "restrictions": blocked,
            }

    # ── 3. Compute usage / quota in target region
    quota_resp = _run_az(["vm", "list-usage", "--location", region])
    quotas: List[Dict[str, Any]] = []
    if quota_resp.get("_ok"):
        for u in quota_resp.get("data") or []:
            quotas.append({
                "name":          (u.get("name") or {}).get("localizedValue") or (u.get("name") or {}).get("value"),
                "name_raw":      (u.get("name") or {}).get("value"),
                "current_value": u.get("currentValue"),
                "limit":         u.get("limit"),
            })

    # ── 4. Build issue list
    issues: List[Dict[str, Any]] = []

    # 4a. VM SKU availability check
    for r in vm_resources:
        size = r["size"]
        if not size:
            continue
        info = vm_skus_in_region.get(size)
        if info is None:
            issues.append({
                "severity": "deny",
                "category": "vm_sku",
                "resource": f'{r["type"]}.{r["name"]}',
                "file":     r["file"],
                "detail":   f"VM size '{size}' 가 region '{region}' 에서 제공되지 않습니다",
            })
        elif info["restrictions"]:
            reasons = ", ".join(f'{x["type"]}({x["reason"]})' for x in info["restrictions"])
            issues.append({
                "severity": "deny",
                "category": "vm_sku",
                "resource": f'{r["type"]}.{r["name"]}',
                "file":     r["file"],
                "detail":   f"VM size '{size}' 가 region '{region}' 에서 제한됨: {reasons}",
            })

    # 4b. Policy effect 요약 (deny effect 인 게 있으면 warn)
    deny_policies = [p for p in policies if p.get("enforcement") not in ("DoNotEnforce",)]
    if deny_policies:
        # We don't auto-evaluate policy rules, just surface the count
        issues.append({
            "severity": "warn",
            "category": "policy",
            "resource": "(scope)",
            "file":     "",
            "detail":   f"활성 정책 {len(deny_policies)}개 — apply 시 예측 불가 deny 가능 (아래 목록 검토)",
        })

    # 4c. Quota 단순 비교 — 사용량이 limit-1 이상이면 plan 진행 어려움 (대략)
    for q in quotas:
        try:
            cur = int(q["current_value"])
            lim = int(q["limit"])
            if lim > 0 and cur >= lim:
                issues.append({
                    "severity": "warn",
                    "category": "quota",
                    "resource": q["name_raw"],
                    "file":     "",
                    "detail":   f"quota 한도 도달: {q['name']} = {cur}/{lim}",
                })
        except (TypeError, ValueError):
            pass

    return {
        "subscription_id":  subscription_id,
        "region":           region,
        "tf_resource_count": len(resources),
        "vm_resource_count": len(vm_resources),
        "vm_sizes_wanted":   vm_sizes_wanted,
        "policies":         policies,
        "vm_skus_in_region": vm_skus_in_region,
        "quotas":           quotas,
        "issues":           issues,
        "errors": {
            "policy_list":     pol_resp.get("_error"),
            "vm_list_skus":    vm_sku_resp.get("_error"),
            "vm_list_usage":   quota_resp.get("_error"),
        },
    }
