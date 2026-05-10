"""Azure Policy lookup — fetch enforced Deny/Modify rules for a subscription
including inheritance from management groups.

Adopts the proven recipe from check_policy_rules.py:
  1. REST API ``policyAssignments?api-version=2024-04-01`` returns ALL
     assignments effective on this sub — sub-direct + inherited from MGs.
     (Beats `az policy assignment list` which often misses inherited ones.)
  2. Exemptions are fetched + indexed by (assignmentId, refId) so individual
     initiative inner policies can be marked exempt.
  3. Initiative defs are fetched in parallel (workers=8), then their inner
     policies in a second parallel pass (workers=16).
  4. Effect resolution follows the parameter chain:
       assignment.parameters → initiative-supplied sub_params → definition default
     so `[parameters('effect')]` references resolve to the actually-applied effect.
  5. dedup by `policyDefinitionId|effect` (same policy in multiple initiatives → once).

Output (extract_constraints) keeps the same shape downstream generators /
policy_compliance.py already consume.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cache the (potentially expensive) per-subscription full assignment list
# for an hour.  Policies don't change often within a deploy session.
_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_LOCK = Lock()
_TTL = 3600


def _az_rest(url: str, timeout: int = 60) -> Dict[str, Any]:
    """Direct ARM REST call via ``az rest --method get``.  Returns parsed JSON
    or empty dict on any failure.  Mirrors the pattern from check_policy_rules.py
    — REST is more reliable than `az policy *` subcommands for inherited and
    cross-MG visibility."""
    try:
        proc = subprocess.run(
            ["az", "rest", "--method", "get", "--url", url, "-o", "json"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("az rest exception (%s): %s", url[:120], e)
        return {}
    if proc.returncode != 0:
        logger.debug("az rest rc=%s for %s: %s", proc.returncode, url[:120], (proc.stderr or "")[-300:])
        return {}
    try:
        return json.loads(proc.stdout) if proc.stdout else {}
    except json.JSONDecodeError:
        return {}


def _get_policy_definition_rest(def_id: str) -> Dict[str, Any]:
    if not def_id:
        return {}
    url = f"https://management.azure.com{def_id}?api-version=2021-06-01"
    return _az_rest(url)


def _resolve_effect(policy_props: Dict[str, Any],
                    sub_params: Dict[str, Any],
                    assign_params: Dict[str, Any]) -> str:
    """Resolve a policy's effective effect along the parameter chain.

    Priority: assignment params > initiative sub_params > definition default.
    """
    rule = policy_props.get("policyRule", {}) or {}
    pol_params = policy_props.get("parameters", {}) or {}
    effect_expr = ((rule.get("then") or {}).get("effect") or "")
    if not isinstance(effect_expr, str):
        return ""
    if not effect_expr.startswith("[parameters("):
        return effect_expr.lower()
    param_name = effect_expr.replace("[parameters('", "").replace("')]", "")
    if param_name in (assign_params or {}) and "value" in assign_params[param_name]:
        return str(assign_params[param_name]["value"]).lower()
    if param_name in (sub_params or {}) and "value" in sub_params[param_name]:
        return str(sub_params[param_name]["value"]).lower()
    if param_name in pol_params and "defaultValue" in pol_params[param_name]:
        return str(pol_params[param_name]["defaultValue"]).lower()
    return "unknown"


def _extract_policy_condition(policy_props: Dict[str, Any]) -> Dict[str, Any]:
    """Walk the if-clause to find target resource type + field conditions."""
    rule = policy_props.get("policyRule", {}) or {}
    condition = rule.get("if") or {}
    resource_type: Optional[str] = None
    fields: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        nonlocal resource_type
        if isinstance(node, dict):
            if node.get("field") == "type" and "equals" in node:
                resource_type = node["equals"]
            elif "field" in node and node["field"] != "type":
                f = node["field"]
                for op in ["equals", "notEquals", "in", "notIn", "contains",
                           "notContains", "like", "notLike", "greater",
                           "greaterOrEquals", "less", "lessOrEquals", "exists"]:
                    if op in node:
                        fields.append({"field": f, "operator": op, "value": node[op]})
                        break
            for key in ("allOf", "anyOf", "AnyOf", "not"):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(condition)
    return {"resourceType": resource_type or "Unknown", "conditions": fields}


def _extract_modify_operations(policy_props: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For Modify effect, return [{field, operation, value}, ...]."""
    rule = policy_props.get("policyRule", {}) or {}
    details = (rule.get("then") or {}).get("details") or {}
    ops = details.get("operations") if isinstance(details, dict) else []
    out = []
    for op in ops or []:
        out.append({
            "field":     op.get("field", ""),
            "operation": op.get("operation", ""),
            "value":     op.get("value"),
        })
    return out


def _build_exemption_index(exemptions: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Index exemptions by (assignmentId_lower, refId_lower or '*'); skip expired."""
    index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    now = datetime.now(timezone.utc)
    for e in exemptions or []:
        props = e.get("properties", {}) or {}
        assignment_id = (props.get("policyAssignmentId", "") or "").lower()
        ref_ids = props.get("policyDefinitionReferenceIds", []) or []
        expires_on = props.get("expiresOn", "")
        if expires_on:
            try:
                exp = datetime.fromisoformat(expires_on.replace("Z", "+00:00"))
                if exp < now:
                    continue
            except ValueError:
                pass
        info = {
            "displayName": props.get("displayName") or e.get("name", ""),
            "category":    props.get("exemptionCategory", ""),
            "expiresOn":   expires_on or "없음",
        }
        if ref_ids:
            for ref_id in ref_ids:
                index[(assignment_id, ref_id.lower())].append(info)
        else:
            index[(assignment_id, "*")].append(info)
    return index


def _find_exemption(idx: Dict[Tuple[str, str], List[Dict[str, Any]]],
                    assignment_id: str, ref_id: str) -> List[Dict[str, Any]]:
    aid = (assignment_id or "").lower()
    rid = (ref_id or "").lower()
    matches: List[Dict[str, Any]] = []
    if rid and (aid, rid) in idx:
        matches.extend(idx[(aid, rid)])
    if (aid, "*") in idx:
        matches.extend(idx[(aid, "*")])
    return matches


def _fetch_enforced_rules(subscription_id: str) -> Dict[str, Any]:
    """Adopt the exact recipe from check_policy_rules.py — return raw deny/modify
    rule list with exemption flags + summary counts.

    Returns dict:
        {
          "rules":     [<rule>, ...],
          "exempt":    int,
          "assignments_count": int,
          "exemptions_count":  int,
        }
    Each <rule>:
        {effect, policyName, assignmentName, assignmentId, referenceId,
         scope, scopeLabel, policyDefinitionId, resourceType, conditions,
         modifyOperations, exemptions, isExempt}
    """
    target_effects = {"deny", "modify"}

    # 1. Assignments (REST gives us inherited from MGs)
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Authorization/policyAssignments"
        f"?api-version=2024-04-01"
    )
    assignments = (_az_rest(url) or {}).get("value", [])

    # 1b. Exemptions
    exempt_url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Authorization/policyExemptions"
        f"?api-version=2022-07-01-preview"
    )
    exemptions = (_az_rest(exempt_url) or {}).get("value", [])
    exemption_index = _build_exemption_index(exemptions)

    # 2a. Split into initiatives vs single policies + parallel-fetch initiatives
    initiative_futures = {}
    single_policies = []
    sub_def_tasks: List[Tuple[str, Dict[str, Any], str, str, str, Dict[str, Any], str]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        for a in assignments:
            props = a.get("properties", {}) or {}
            pdid = props.get("policyDefinitionId", "")
            if "/policySetDefinitions/" in pdid:
                initiative_futures[pool.submit(_get_policy_definition_rest, pdid)] = a
            else:
                single_policies.append(a)

        for fut in as_completed(initiative_futures):
            a = initiative_futures[fut]
            props = a.get("properties", {}) or {}
            assign_name = props.get("displayName", "") or a.get("name", "")
            scope = props.get("scope", "")
            assign_params = props.get("parameters", {}) or {}
            set_data = fut.result() or {}
            set_props = set_data.get("properties", {}) or {}
            assign_id = a.get("id", "")
            for sd in set_props.get("policyDefinitions", []) or []:
                sub_def_tasks.append((
                    sd.get("policyDefinitionId", ""),
                    sd.get("parameters", {}) or {},
                    sd.get("policyDefinitionReferenceId", ""),
                    assign_name, scope, assign_params, assign_id,
                ))

    # Append single policies as tasks too (uniform processing)
    for a in single_policies:
        props = a.get("properties", {}) or {}
        sub_def_tasks.append((
            props.get("policyDefinitionId", ""),
            {},
            "",
            props.get("displayName", "") or a.get("name", ""),
            props.get("scope", ""),
            props.get("parameters", {}) or {},
            a.get("id", ""),
        ))

    # 2b. Parallel-fetch all individual policy defs and post-process
    def _process(task: Tuple[str, Dict[str, Any], str, str, str, Dict[str, Any], str]) -> Optional[Dict[str, Any]]:
        sub_def_id, sub_params, ref_id, assign_name, scope, assign_params, assign_id = task
        pol = _get_policy_definition_rest(sub_def_id) or {}
        pol_props = pol.get("properties", {}) or {}
        if not pol_props:
            return None
        effect = _resolve_effect(pol_props, sub_params, assign_params)
        if effect not in target_effects:
            return None
        cond = _extract_policy_condition(pol_props)
        modify_ops = _extract_modify_operations(pol_props) if effect == "modify" else []
        exemptions_found = _find_exemption(exemption_index, assign_id, ref_id)
        return {
            "effect":             effect.upper(),                  # "DENY" / "MODIFY"
            "policyName":         pol_props.get("displayName") or ref_id,
            "description":        pol_props.get("description", ""),
            "assignmentName":     assign_name,
            "assignmentId":       assign_id,
            "referenceId":        ref_id,
            "scope":              scope,
            "policyDefinitionId": sub_def_id,
            "resourceType":       cond["resourceType"],
            "conditions":         cond["conditions"],
            "modifyOperations":   modify_ops,
            "exemptions":         exemptions_found,
            "isExempt":           len(exemptions_found) > 0,
        }

    rules: List[Dict[str, Any]] = []
    seen: set = set()
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(_process, t) for t in sub_def_tasks]
        for fut in as_completed(futs):
            r = fut.result()
            if r is None:
                continue
            key = f"{r['policyDefinitionId']}|{r['effect']}"
            if key in seen:
                continue
            seen.add(key)
            rules.append(r)

    exempt_count = sum(1 for r in rules if r["isExempt"])
    logger.info(
        "policy: sub=%s assignments=%d exemptions=%d rules=%d exempt=%d",
        subscription_id, len(assignments), len(exemptions), len(rules), exempt_count,
    )
    return {
        "rules":              rules,
        "assignments_count":  len(assignments),
        "exemptions_count":   len(exemptions),
        "exempt":             exempt_count,
    }


def _az(args: List[str], timeout: int = 60) -> Any:
    """Run an `az` command and return parsed JSON, or None on failure."""
    cmd = ["az"] + args + ["-o", "json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if r.returncode != 0 or not r.stdout:
        if r is not None and r.stderr:
            logger.debug("az %s failed: %s", " ".join(args), r.stderr.strip()[-300:])
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


_GRAPH_LAST_ERROR: Optional[str] = None  # last failure reason for diagnostics


def _az_graph(query: str, timeout: int = 90) -> List[Dict[str, Any]]:
    """Run an Azure Resource Graph query and return its rows.

    Uses default page size — `--first` removed so we don't artificially cap
    results.  If the result has a continuation token we follow it (paged).
    Records the last failure reason in ``_GRAPH_LAST_ERROR`` for diagnostics.
    """
    global _GRAPH_LAST_ERROR
    _GRAPH_LAST_ERROR = None
    rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None
    for page in range(20):   # at most 20 pages defensively
        args = ["az", "graph", "query", "-q", query, "-o", "json"]
        if skip_token:
            args += ["--skip-token", skip_token]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            _GRAPH_LAST_ERROR = f"graph query exception: {e}"
            return rows
        if r.returncode != 0:
            stderr = (r.stderr or "").strip()
            if "is not in the" in stderr.lower() or "not recognized" in stderr.lower() or "extension" in stderr.lower():
                _GRAPH_LAST_ERROR = "resource-graph extension not installed (run: az extension add --name resource-graph)"
            else:
                _GRAPH_LAST_ERROR = f"graph rc={r.returncode}: {stderr[-300:]}"
            logger.warning("az graph query failed: %s", _GRAPH_LAST_ERROR)
            return rows
        try:
            parsed = json.loads(r.stdout) if r.stdout else None
        except json.JSONDecodeError as e:
            _GRAPH_LAST_ERROR = f"graph output not JSON: {e}"
            return rows
        if parsed is None:
            break
        # `az graph query -o json` returns either:
        #  • a list of rows directly, OR
        #  • a dict {data: [...], skip_token: ...} (with paging metadata)
        if isinstance(parsed, list):
            rows.extend(parsed)
            break
        if isinstance(parsed, dict):
            rows.extend(parsed.get("data") or [])
            skip_token = parsed.get("skip_token") or parsed.get("skipToken")
            if not skip_token:
                break
        else:
            break
    return rows


def _fetch_assignments_via_graph(subscription_id: str) -> List[Dict[str, Any]]:
    """All enforced policy assignments at this subscription scope, including
    inheritance from management groups above the subscription.

    Resource Graph captures the full inheritance chain in one query (vs.
    `az policy assignment list` which only sees a single scope), so this is
    both more accurate and faster.  Then we fetch each unique definition
    once via Resource Graph as well — N+1 collapses to 2 graph calls.
    """
    sub_id_lower = subscription_id.lower()
    # 1) All enforced assignments at sub or any parent management group scope.
    #    Use a flat project (no extend) — some KQL parser configurations
    #    choke on chained `extend` clauses with reserved-ish names like
    #    `scope` / `enforcement`, so we inline expressions instead.
    q_assign = f"""
policyresources
| where type =~ 'microsoft.authorization/policyassignments'
| where tostring(properties.enforcementMode) != 'DoNotEnforce'
| where tolower(tostring(properties.scope)) startswith '/subscriptions/{sub_id_lower}' or tolower(tostring(properties.scope)) startswith '/providers/microsoft.management/managementgroups'
| project assignmentName = name, displayName = tostring(properties.displayName), assignmentScope = tolower(tostring(properties.scope)), defId = tostring(properties.policyDefinitionId), parameters = properties.parameters, notScopes = properties.notScopes
""".strip()
    assignments = _az_graph(q_assign)
    if not assignments:
        return []

    # 2) Resolve every referenced definition.  Run TWO queries (policy +
    #    policySet) instead of one combined — projecting `type` as a column
    #    inside `project` (e.g. `kind = type`) trips some KQL parser builds
    #    with a confusing "ParserFailure ... token =" error.
    def_ids = sorted({(a.get("defId") or "").lower() for a in assignments if a.get("defId")})
    if not def_ids:
        return []
    def_index: Dict[str, Dict[str, Any]] = {}
    for chunk_start in range(0, len(def_ids), 100):
        chunk = def_ids[chunk_start:chunk_start + 100]
        ids_kql = ", ".join(f"'{x}'" for x in chunk)
        # Plain policies
        q_pol = f"""
policyresources
| where type =~ 'microsoft.authorization/policydefinitions'
| where tolower(id) in ({ids_kql})
| project lowerId = tolower(id), definitionName = name, displayName = tostring(properties.displayName), policyType = tostring(properties.policyType), policyRule = properties.policyRule, metadata = properties.metadata
""".strip()
        for row in _az_graph(q_pol):
            row["kind"] = "microsoft.authorization/policydefinitions"
            def_index[row["lowerId"]] = row
        # Policy-sets (initiatives)
        q_set = f"""
policyresources
| where type =~ 'microsoft.authorization/policysetdefinitions'
| where tolower(id) in ({ids_kql})
| project lowerId = tolower(id), definitionName = name, displayName = tostring(properties.displayName), policyDefinitions = properties.policyDefinitions, metadata = properties.metadata
""".strip()
        for row in _az_graph(q_set):
            row["kind"] = "microsoft.authorization/policysetdefinitions"
            def_index[row["lowerId"]] = row

    # 3) Flatten initiatives into individual policy entries (matching prior
    #    shape so policies_for_resource_type / extract_constraints keep working).
    out: List[Dict[str, Any]] = []
    inner_to_resolve: List[str] = []
    inner_assignments: List[tuple] = []   # (inner_def_id, parent_assignment_dict, inner_params)

    for a in assignments:
        defn = def_index.get((a.get("defId") or "").lower())
        if defn is None:
            # We saw an assignment but couldn't resolve the definition (rare —
            # cross-tenant or RBAC issue).  Surface the assignment minimally.
            out.append({
                "assignment_name":    a.get("assignmentName"),
                "assignment_display": a.get("displayName"),
                "scope":              a.get("assignmentScope"),
                "definition":         {"id": a.get("defId"), "displayName": a.get("displayName")},
                "parameters":         a.get("parameters") or {},
                "from_initiative":    None,
            })
            continue

        if defn.get("kind") == "microsoft.authorization/policysetdefinitions":
            # Initiative: queue inner definitions to fetch
            for pd in (defn.get("policyDefinitions") or []):
                inner_id = (pd.get("policyDefinitionId") or "").lower()
                if not inner_id:
                    continue
                inner_to_resolve.append(inner_id)
                inner_assignments.append((inner_id, a, pd.get("parameters") or {}))
        else:
            out.append({
                "assignment_name":    a.get("assignmentName"),
                "assignment_display": a.get("displayName"),
                "scope":              a.get("assignmentScope"),
                "definition":         {
                    "id":          defn.get("lowerId"),
                    "displayName": defn.get("displayName"),
                    "name":        defn.get("definitionName"),
                    "policyRule":  defn.get("policyRule"),
                    "metadata":    defn.get("metadata"),
                },
                "parameters":      a.get("parameters") or {},
                "from_initiative": None,
            })

    # 4) Resolve inner-initiative definitions in chunks
    if inner_to_resolve:
        unique_inner = sorted(set(inner_to_resolve))
        inner_index: Dict[str, Dict[str, Any]] = {}
        for chunk_start in range(0, len(unique_inner), 100):
            chunk = unique_inner[chunk_start:chunk_start + 100]
            ids_kql = ", ".join(f"'{x}'" for x in chunk)
            q = f"""
policyresources
| where type =~ 'microsoft.authorization/policydefinitions'
| where tolower(id) in ({ids_kql})
| project lowerId = tolower(id), definitionName = name, displayName = tostring(properties.displayName), policyRule = properties.policyRule, metadata = properties.metadata
""".strip()
            for row in _az_graph(q):
                inner_index[row["lowerId"]] = row

        for inner_id, parent_a, inner_params in inner_assignments:
            inner = inner_index.get(inner_id)
            if not inner:
                continue
            out.append({
                "assignment_name":    parent_a.get("assignmentName"),
                "assignment_display": parent_a.get("displayName"),
                "scope":              parent_a.get("assignmentScope"),
                "definition":         {
                    "id":          inner.get("lowerId"),
                    "displayName": inner.get("displayName"),
                    "name":        inner.get("definitionName"),
                    "policyRule":  inner.get("policyRule"),
                    "metadata":    inner.get("metadata"),
                },
                "parameters":      inner_params,
                "from_initiative": (parent_a.get("defId") or "").rsplit("/", 1)[-1],
            })

    logger.info(
        "policy graph: %d assignments → %d resolved policies (sub=%s)",
        len(assignments), len(out), subscription_id,
    )
    return out


def _show_policy_definition(defn_id: str, subscription_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single policy definition by its definitionId.

    Tries the right CLI subcommand based on where the def lives:
      - sub-scope custom:    ``--name <n> --subscription <sub>``
      - mgmt-group-scope:    ``--name <n> --management-group <mg>``
      - built-in / providers: just ``--name <n>``
    Returns None on any failure so callers can keep going.
    """
    name = defn_id.rsplit("/", 1)[-1]
    if not name:
        return None
    args = ["policy", "definition", "show", "--name", name]
    low = defn_id.lower()
    if "/subscriptions/" in low:
        # custom def at sub scope — must pass --subscription
        try:
            sub_seg = defn_id.split("/subscriptions/", 1)[1].split("/", 1)[0]
            args += ["--subscription", sub_seg or subscription_id]
        except Exception:
            args += ["--subscription", subscription_id]
    elif "/managementgroups/" in low:
        try:
            mg = defn_id.split("/managementGroups/", 1)[1].split("/", 1)[0]
            args += ["--management-group", mg]
        except Exception:
            pass
    return _az(args)


def _show_set_definition(defn_id: str, subscription_id: str) -> Optional[Dict[str, Any]]:
    name = defn_id.rsplit("/", 1)[-1]
    if not name:
        return None
    args = ["policy", "set-definition", "show", "--name", name]
    low = defn_id.lower()
    if "/subscriptions/" in low:
        try:
            sub_seg = defn_id.split("/subscriptions/", 1)[1].split("/", 1)[0]
            args += ["--subscription", sub_seg or subscription_id]
        except Exception:
            args += ["--subscription", subscription_id]
    elif "/managementgroups/" in low:
        try:
            mg = defn_id.split("/managementGroups/", 1)[1].split("/", 1)[0]
            args += ["--management-group", mg]
        except Exception:
            pass
    return _az(args)


def _fetch_assignments_fallback(subscription_id: str) -> List[Dict[str, Any]]:
    """Fallback path when Resource Graph isn't available (no provider
    registration, RBAC, etc.).  Slower N+1 calls via classic CLI."""
    scope = f"/subscriptions/{subscription_id}"
    raw = _az(["policy", "assignment", "list",
               "--scope", scope, "--disable-scope-strict-match"]) or []
    out: List[Dict[str, Any]] = []
    for a in raw:
        if a.get("enforcementMode") == "DoNotEnforce":
            continue
        pdid = a.get("policyDefinitionId") or ""
        if "/policySetDefinitions/" in pdid:
            initiative = _show_set_definition(pdid, subscription_id)
            if initiative and isinstance(initiative.get("policyDefinitions"), list):
                for pd in initiative["policyDefinitions"]:
                    inner_id = pd.get("policyDefinitionId") or ""
                    if not inner_id:
                        continue
                    inner = _show_policy_definition(inner_id, subscription_id)
                    if inner:
                        out.append({
                            "assignment_name":    a.get("name"),
                            "assignment_display": a.get("displayName"),
                            "scope":              a.get("scope"),
                            "definition":         inner,
                            "parameters":         pd.get("parameters") or {},
                            "from_initiative":    pdid.rsplit("/", 1)[-1],
                        })
            continue
        defn = _show_policy_definition(pdid, subscription_id)
        if defn:
            out.append({
                "assignment_name":    a.get("name"),
                "assignment_display": a.get("displayName"),
                "scope":              a.get("scope"),
                "definition":         defn,
                "parameters":         a.get("parameters") or {},
                "from_initiative":    None,
            })
    return out


def _fetch_blocking_defs_via_graph(subscription_id: str) -> List[Dict[str, Any]]:
    """All policy definitions visible to us with deny/denyAction/modify/append
    effects, scoped to:
      • this subscription's custom defs:  /subscriptions/<sub>/providers/...
      • any management group def visible:  /providers/microsoft.management/managementgroups/...
      • built-ins:                         /providers/microsoft.authorization/policydefinitions/...

    Built-ins are typically only relevant if assigned, but a custom def in our
    sub or in an upstream management group is a strong signal — even if our
    assignment query missed an indirect reference (Defender, Initiative inner,
    inherited assignment), having the definition in scope means the constraint
    likely applies.  Each entry here is later merged into field_operations
    with ``source = "available_in_scope"`` so downstream can distinguish.
    """
    sub_id_lower = subscription_id.lower()
    # We deliberately do NOT filter by `effect in (...)` in the where clause —
    # it lives under properties.policyRule.then.effect and projecting it inside
    # `where` after a project is more reliable than using nested tostring()
    # in `where`.  Filter in Python after project.
    q = f"""
policyresources
| where type =~ 'microsoft.authorization/policydefinitions'
| where tolower(id) startswith '/subscriptions/{sub_id_lower}/' or tolower(id) startswith '/providers/microsoft.management/managementgroups/'
| project lowerId = tolower(id), definitionName = name, displayName = tostring(properties.displayName), policyType = tostring(properties.policyType), policyRule = properties.policyRule, metadata = properties.metadata
""".strip()
    rows = _az_graph(q)
    out: List[Dict[str, Any]] = []
    for r in rows:
        rule = r.get("policyRule") if isinstance(r.get("policyRule"), dict) else {}
        effect = (rule.get("then") or {}).get("effect")
        if isinstance(effect, str) and effect.startswith("[parameters("):
            # Parameter ref — without an assignment we can't resolve, but
            # the definition's *default* often reveals the intended effect.
            params = (rule.get("parameters") or {})
            try:
                pname = effect.split("'")[1]
                pdef = params.get(pname) or {}
                default = pdef.get("defaultValue") or pdef.get("default_value")
                if isinstance(default, str):
                    effect = default
            except Exception:
                pass
        if not isinstance(effect, str):
            continue
        if effect.lower() not in ("deny", "denyaction", "modify", "append"):
            continue
        out.append(r)
    return out


def _has_real_rule(entry: Dict[str, Any]) -> bool:
    """Did this assignment entry actually carry a usable policyRule?"""
    return bool(_get_policy_rule(entry.get("definition") or {}).get("if"))


# Records which path actually populated the assignment cache (graph / fallback).
_LAST_FETCH_PATH: Optional[str] = None


def _fetch_assignments(subscription_id: str) -> List[Dict[str, Any]]:
    """Try Resource Graph first (fast + management-group inheritance); fall
    back to per-assignment CLI calls if Graph is unavailable OR if Graph
    only returned stubs (assignments without resolved definitions, which
    happens when the definitions sub-query fails parser checks)."""
    global _LAST_FETCH_PATH
    via_graph = _fetch_assignments_via_graph(subscription_id)
    real_rules = sum(1 for e in via_graph if _has_real_rule(e))
    if via_graph and real_rules > 0:
        _LAST_FETCH_PATH = "graph"
        return via_graph
    if via_graph:
        logger.info(
            "policy graph: returned %d stubs without rules — supplementing with CLI fallback for sub=%s",
            len(via_graph), subscription_id,
        )
        _LAST_FETCH_PATH = "fallback (graph stub-only)"
    else:
        logger.info("policy graph empty/failed — using CLI fallback for sub=%s", subscription_id)
        _LAST_FETCH_PATH = "fallback (graph empty)"
    return _fetch_assignments_fallback(subscription_id)


def _get_assignments_cached(subscription_id: str) -> List[Dict[str, Any]]:
    now = time.time()
    with _LOCK:
        cached = _CACHE.get(subscription_id)
        if cached and (now - cached[0]) < _TTL:
            return cached[1]
    fetched = _fetch_assignments(subscription_id)
    with _LOCK:
        _CACHE[subscription_id] = (now, fetched)
    return fetched


# ── Type filter logic ──────────────────────────────────────────

def _rule_mentions_type(node: Any, az_type: str) -> bool:
    """True if any nested clause checks `field == "type"` with this Azure type."""
    if isinstance(node, dict):
        if (node.get("field") or "").lower() == "type":
            for op_key in ("equals", "notEquals"):
                v = node.get(op_key)
                if isinstance(v, str) and v.lower() == az_type.lower():
                    return True
            for op_key in ("in", "notIn"):
                v = node.get(op_key) or []
                if isinstance(v, list) and any(isinstance(x, str) and x.lower() == az_type.lower() for x in v):
                    return True
        return any(_rule_mentions_type(v, az_type) for v in node.values())
    if isinstance(node, list):
        return any(_rule_mentions_type(item, az_type) for item in node)
    return False


def _rule_has_any_type_check(node: Any) -> bool:
    """True if anywhere in the rule tree there's a `field: "type"` check."""
    if isinstance(node, dict):
        if (node.get("field") or "").lower() == "type":
            return True
        return any(_rule_has_any_type_check(v) for v in node.values())
    if isinstance(node, list):
        return any(_rule_has_any_type_check(item) for item in node)
    return False


def _summarize_rule(node: Any, depth: int = 0) -> str:
    """Best-effort one-line description of a policyRule.if clause."""
    if depth > 4:
        return "..."
    if isinstance(node, dict):
        f = node.get("field") or node.get("source") or node.get("value")
        for op in ("equals", "notEquals", "in", "notIn", "contains", "like", "match", "exists"):
            if op in node and f:
                v = node[op]
                if isinstance(v, list) and len(v) > 6:
                    v = v[:6] + ["…"]
                return f"{f} {op} {v}"
        for joiner_key, joiner in (("allOf", " AND "), ("anyOf", " OR ")):
            if joiner_key in node:
                items = node[joiner_key] if isinstance(node[joiner_key], list) else [node[joiner_key]]
                return "(" + joiner.join(_summarize_rule(i, depth + 1) for i in items[:6]) + ")"
        if "not" in node:
            return "NOT(" + _summarize_rule(node["not"], depth + 1) + ")"
    if isinstance(node, list):
        return "[" + ", ".join(_summarize_rule(i, depth + 1) for i in node[:6]) + "]"
    s = str(node)
    return s if len(s) < 120 else s[:120] + "…"


def policies_for_resource_type(subscription_id: str, azure_type: str) -> List[Dict[str, Any]]:
    """Filter policies down to those that affect ``azure_type`` (e.g.
    "Microsoft.Compute/virtualMachines").

    Returned shape (kept compact for LLM context):
        [
          {
            "name": "<display_name or name>",
            "effect": "deny" | "audit" | "modify" | "append" | ...,
            "scope_kind": "type-specific" | "universal",
            "rule": "<one-line summary>",
            "parameters": { ... values for this assignment ... },
            "definition_id": "...",
          },
          ...
        ]
    """
    assignments = _get_assignments_cached(subscription_id)
    out: List[Dict[str, Any]] = []
    for a in assignments:
        defn = a.get("definition") or {}
        policy_rule = _get_policy_rule(defn)
        rule = policy_rule.get("if")
        if rule is None:
            continue
        is_type_specific = _rule_mentions_type(rule, azure_type)
        is_universal     = not _rule_has_any_type_check(rule)
        if not (is_type_specific or is_universal):
            continue
        effect = (policy_rule.get("then") or {}).get("effect")
        # Effect can itself be a parameter reference like "[parameters('effect')]"
        if isinstance(effect, str) and effect.startswith("[parameters("):
            param_name = effect.split("'")[1] if "'" in effect else None
            if param_name and isinstance(a.get("parameters"), dict):
                pv = a["parameters"].get(param_name)
                if isinstance(pv, dict):
                    effect = pv.get("value") or effect
        out.append({
            "name":          defn.get("displayName") or defn.get("name") or a.get("assignment_display"),
            "effect":        effect,
            "scope_kind":    "type-specific" if is_type_specific else "universal",
            "rule":          _summarize_rule(rule),
            "parameters":    {
                k: (v.get("value") if isinstance(v, dict) and "value" in v else v)
                for k, v in (a.get("parameters") or {}).items()
            },
            "definition_id": defn.get("id"),
            "from_initiative": a.get("from_initiative"),
        })
    return out


# ── Constraint extraction for terraform code generation ──────

# Built-in policy IDs we know how to interpret deterministically.
# (Most enterprise tenants use these built-ins or copies of them.)
_BUILTIN_REQUIRE_TAG       = "1e30110a-5ceb-460c-a204-c1c3969c6d62"   # Require a tag on resources
_BUILTIN_REQUIRE_TAG_VALUE = "cd8dc879-a2ae-43c3-8211-1877c5755064"   # Require a tag and its value on resources
_BUILTIN_APPEND_TAG_VALUE  = "49c88fc8-6fd1-46fd-a676-f12d1d3a4c71"   # Append a tag and its value to resources
_BUILTIN_REQUIRE_TAG_RG    = "96670d01-0a4d-4649-9c89-2d3abc0a5025"   # Require a tag on resource groups
_BUILTIN_ALLOWED_LOCATIONS = "e56962a6-4747-49cd-b67b-bf8b01975c4c"   # Allowed locations
_BUILTIN_ALLOWED_LOC_RG    = "e765b5de-1225-4ba3-bd56-1ac6695af988"   # Allowed locations for resource groups


def _builtin_id(definition_id: str) -> str:
    """Extract the trailing GUID from a policy definition ID."""
    return (definition_id or "").rsplit("/", 1)[-1].lower()


def _get_policy_rule(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Return the policyRule dict regardless of az CLI version (some flatten
    `properties.policyRule` to top-level, some keep it nested)."""
    if not isinstance(defn, dict):
        return {}
    rule = defn.get("policyRule")
    if isinstance(rule, dict) and rule:
        return rule
    nested = (defn.get("properties") or {}).get("policyRule") if isinstance(defn.get("properties"), dict) else None
    return nested if isinstance(nested, dict) else {}


def _find_target_type(node: Any) -> Optional[str]:
    """Walk the rule.if tree and return the first `field == "type"` value
    (modify/append policies always have one in practice — that's the type
    they constrain).  Returns None for universal policies."""
    if isinstance(node, dict):
        if (node.get("field") or "").lower() == "type":
            v = node.get("equals")
            if isinstance(v, str):
                return v
            v_in = node.get("in") or []
            if isinstance(v_in, list) and v_in and isinstance(v_in[0], str):
                return v_in[0]
            return None
        for sub in node.values():
            r = _find_target_type(sub)
            if r:
                return r
    elif isinstance(node, list):
        for sub in node:
            r = _find_target_type(sub)
            if r:
                return r
    return None


def _extract_modify_append_ops(policy_rule: Dict[str, Any], effect: str) -> List[Dict[str, Any]]:
    """Return the list of {field, value, [operation]} ops for modify/append.

    modify ⇒  rule.then.details.operations
    append ⇒  rule.then.details (a list itself)
    """
    if not isinstance(policy_rule, dict):
        return []
    then = policy_rule.get("then") or {}
    details = then.get("details")
    if effect == "modify" and isinstance(details, dict):
        return list(details.get("operations") or [])
    if effect == "append" and isinstance(details, list):
        return list(details)
    return []


def _resolve_param_value(param_ref: Any, params: Dict[str, Any]) -> Any:
    """Replace `[parameters('foo')]` with the assignment's actual value."""
    if isinstance(param_ref, str) and param_ref.startswith("[parameters("):
        # crude — extract the inner name
        name = param_ref.split("'")[1] if "'" in param_ref else None
        if name and isinstance(params.get(name), dict) and "value" in params[name]:
            return params[name]["value"]
        if name and name in params:
            return params[name]
    return param_ref


def extract_constraints(subscription_id: str) -> Dict[str, Any]:
    """Adopt check_policy_rules.py logic — REST + parallel + exemptions +
    parameter chain resolution.  Output schema unchanged so generators and
    policy_compliance.py keep consuming the same fields.

    Returns:
        {
          "required_tags":     [...],   # heuristic from common deny rules
          "tag_defaults":      {...},
          "allowed_locations": [...],
          "manual_review":     [...],   # active DENY rules (terraform must avoid)
          "field_operations":  [...],   # active MODIFY rules → for LLM patch pass
          "subscription_id":   "...",
          "diagnostics":       {...},
        }
    """
    fetched = _fetch_enforced_rules(subscription_id)
    rules = fetched["rules"]

    required_tags: List[str] = []
    tag_defaults: Dict[str, str] = {}
    allowed_locations: List[str] = []
    manual_review: List[Dict[str, Any]] = []
    field_operations: List[Dict[str, Any]] = []

    type_targets: List[str] = []  # for diagnostics

    for r in rules:
        if r.get("isExempt"):
            continue
        effect_l = (r.get("effect") or "").lower()
        rt = r.get("resourceType") or "Unknown"

        if effect_l == "modify":
            ops = r.get("modifyOperations") or []
            if not ops:
                continue
            field_operations.append({
                "policy_name": r.get("policyName"),
                "azure_type":  rt if rt != "Unknown" else None,
                "effect":      "modify",
                "operations":  ops,
                "scope":       r.get("scope"),
                "source":      "enforced_assignment",
            })
            type_targets.append(rt)

        elif effect_l == "deny":
            # Best-effort built-in heuristics for tag/location requirements.
            # The user's check_policy_rules.py doesn't try to map these to
            # var.tags / var.location, but our generators benefit from it.
            cond_text = " ".join(
                str(c.get("field", "")) for c in (r.get("conditions") or [])
            ).lower()
            # Allowed locations heuristic — not all policies expose this in a
            # parseable way; we just surface deny entries to manual_review and
            # let the LLM compliance pass interpret.  Tag-required policies
            # whose conditions reference `tags['X']` get added to required_tags.
            for cond in r.get("conditions") or []:
                f = str(cond.get("field", ""))
                if f.startswith("tags['") or f.startswith("tags["):
                    # extract X from tags['X'] or tags[X]
                    try:
                        inner = f.split("[", 1)[1].split("]", 1)[0]
                        tag_name = inner.strip("'\"")
                        if tag_name and tag_name not in required_tags:
                            required_tags.append(tag_name)
                    except Exception:
                        pass

            manual_review.append({
                "name":         r.get("policyName"),
                "effect":       "deny",
                "resourceType": rt,
                "rule":         f"DENY {rt}: " + ", ".join(
                    f'{c.get("field")} {c.get("operator")} {c.get("value")}'
                    for c in (r.get("conditions") or [])[:4]
                ),
                "scope":        r.get("scope"),
                "source":       "enforced_assignment",
            })

    # Diagnostics
    raw_effects = sorted({(r.get("effect") or "").upper() for r in rules})
    deny_count   = sum(1 for r in rules if (r.get("effect") or "").lower() == "deny" and not r.get("isExempt"))
    modify_count = sum(1 for r in rules if (r.get("effect") or "").lower() == "modify" and not r.get("isExempt"))
    diagnostics = {
        "fetch_path":           "rest+parallel (check_policy_rules.py-style)",
        "raw_assignment_count": fetched.get("assignments_count", 0),
        "exemptions_count":     fetched.get("exemptions_count", 0),
        "rule_count":           len(rules),
        "exempt_rule_count":    fetched.get("exempt", 0),
        "deny_count":           deny_count,
        "modify_count":         modify_count,
        "modify_target_types":  sorted(set(type_targets)),
        "effects_seen":         raw_effects,
    }

    return {
        "required_tags":     required_tags,
        "tag_defaults":      tag_defaults,
        "allowed_locations": allowed_locations,
        "manual_review":     manual_review,
        "field_operations":  field_operations,
        "subscription_id":   subscription_id,
        "diagnostics":       diagnostics,
    }


def _legacy_extract_constraints(subscription_id: str) -> Dict[str, Any]:
    """Legacy graph-based extractor — kept as a fallback path only.  The
    canonical implementation is ``extract_constraints`` below which uses
    the REST/parallel pipeline matching check_policy_rules.py."""
    assignments = _get_assignments_cached(subscription_id)
    required_tags: List[str] = []
    tag_defaults: Dict[str, str] = {}
    allowed_locations: List[str] = []
    manual_review: List[Dict[str, Any]] = []
    field_operations: List[Dict[str, Any]] = []   # modify/append → terraform attribute patches

    for a in assignments:
        defn = a.get("definition") or {}
        bid = _builtin_id(defn.get("id", ""))
        params = a.get("parameters") or {}

        if bid in (_BUILTIN_REQUIRE_TAG, _BUILTIN_REQUIRE_TAG_RG):
            tn = params.get("tagName")
            tn_val = (tn or {}).get("value") if isinstance(tn, dict) else tn
            if tn_val and tn_val not in required_tags:
                required_tags.append(tn_val)
            continue

        if bid in (_BUILTIN_REQUIRE_TAG_VALUE, _BUILTIN_APPEND_TAG_VALUE):
            tn = params.get("tagName")
            tv = params.get("tagValue")
            tn_val = (tn or {}).get("value") if isinstance(tn, dict) else tn
            tv_val = (tv or {}).get("value") if isinstance(tv, dict) else tv
            if tn_val:
                if tn_val not in required_tags:
                    required_tags.append(tn_val)
                if tv_val:
                    tag_defaults[tn_val] = tv_val
            continue

        if bid in (_BUILTIN_ALLOWED_LOCATIONS, _BUILTIN_ALLOWED_LOC_RG):
            locs = params.get("listOfAllowedLocations")
            locs_val = (locs or {}).get("value") if isinstance(locs, dict) else locs
            if isinstance(locs_val, list):
                for loc in locs_val:
                    if isinstance(loc, str) and loc not in allowed_locations:
                        allowed_locations.append(loc)
            continue

        # Unknown / custom policy — extract structured info we can act on.
        policy_rule = _get_policy_rule(defn)
        rule = policy_rule.get("if")
        effect = (policy_rule.get("then") or {}).get("effect")
        if isinstance(effect, str) and effect.startswith("[parameters("):
            effect = _resolve_param_value(effect, params)
        effect_l = str(effect or "").lower()

        if effect_l in ("deny", "modify", "append", "denyaction"):
            manual_review.append({
                "name":   defn.get("displayName") or defn.get("name"),
                "effect": effect,
                "rule":   _summarize_rule(rule),
            })

        # modify/append carry concrete operations we can feed to the policy
        # compliance LLM pass — extract field/value pairs + the target type.
        if effect_l in ("modify", "append"):
            ops_raw = _extract_modify_append_ops(policy_rule, effect_l)
            # Resolve any "[parameters('...')]" refs inside operation values
            ops: List[Dict[str, Any]] = []
            for op in ops_raw:
                if not isinstance(op, dict):
                    continue
                resolved = dict(op)
                if "value" in resolved:
                    resolved["value"] = _resolve_param_value(resolved["value"], params)
                if "field" in resolved and isinstance(resolved["field"], str):
                    pass  # field path is already concrete
                ops.append(resolved)
            if ops:
                field_operations.append({
                    "policy_name": defn.get("displayName") or defn.get("name"),
                    "azure_type":  _find_target_type(rule),
                    "effect":      effect_l,
                    "operations":  ops,
                })

    # ── Supplemental scan: blocking definitions in scope (assigned or not) ──
    # Even if a custom modify/deny/append def isn't in our enforced assignments
    # list (initiative inner, Defender auto-assigned, mgmt-group inherited that
    # the assignment query missed), the *definition* sitting in this sub or its
    # mgmt group is a strong signal we should comply with.  Pull them via graph
    # and add ones that aren't already covered.
    seen_def_ids = {
        ((a.get("definition") or {}).get("id") or "").lower()
        for a in assignments
    }
    extra_blocking = _fetch_blocking_defs_via_graph(subscription_id)
    extra_used = 0
    for d in extra_blocking:
        did = (d.get("lowerId") or "").lower()
        if did and did in seen_def_ids:
            continue
        rule = d.get("policyRule") if isinstance(d.get("policyRule"), dict) else {}
        effect = (rule.get("then") or {}).get("effect")
        if isinstance(effect, str) and effect.startswith("[parameters("):
            try:
                pname = effect.split("'")[1]
                pdef = (rule.get("parameters") or {}).get(pname) or {}
                effect = pdef.get("defaultValue") or pdef.get("default_value") or effect
            except Exception:
                pass
        if not isinstance(effect, str):
            continue
        eff_l = effect.lower()
        if eff_l not in ("modify", "append"):
            # `deny` 도 manual_review 에 추가
            if eff_l in ("deny", "denyaction"):
                manual_review.append({
                    "name":   d.get("displayName") or d.get("definitionName"),
                    "effect": effect,
                    "rule":   _summarize_rule(rule.get("if")),
                    "source": "available_in_scope",
                })
                extra_used += 1
            continue
        # modify / append — extract operations and add to field_operations
        ops_raw = _extract_modify_append_ops(rule, eff_l)
        if not ops_raw:
            continue
        field_operations.append({
            "policy_name": d.get("displayName") or d.get("definitionName"),
            "azure_type":  _find_target_type(rule.get("if")),
            "effect":      eff_l,
            "operations":  ops_raw,
            "source":      "available_in_scope",
        })
        extra_used += 1

    # Diagnostics: how many raw assignments did we even see, and via which path?
    seen_effects_raw = set()        # before parameter resolution
    seen_effects_resolved = set()   # after parameter resolution
    seen_def_shapes = set()
    modify_targets: List[str] = []  # azure_type for each modify/append we found
    for a in assignments:
        defn = a.get("definition") or {}
        if not defn:
            seen_def_shapes.add("empty")
            continue
        if isinstance(defn.get("policyRule"), dict):
            seen_def_shapes.add("flat")
        elif isinstance((defn.get("properties") or {}).get("policyRule"), dict):
            seen_def_shapes.add("nested")
        else:
            seen_def_shapes.add("no-rule")
        rule = _get_policy_rule(defn)
        eff = (rule.get("then") or {}).get("effect")
        if eff:
            seen_effects_raw.add(str(eff))
            resolved = eff
            if isinstance(eff, str) and eff.startswith("[parameters("):
                resolved = _resolve_param_value(eff, a.get("parameters") or {})
            seen_effects_resolved.add(str(resolved))
            if str(resolved or "").lower() in ("modify", "append"):
                modify_targets.append(_find_target_type(rule.get("if")) or "(any)")
    # Dump the first definition's top-level keys + a sample so we can see what
    # az actually returned when shape detection said 'no-rule'.
    first_sample: Dict[str, Any] = {}
    if assignments:
        first_def = (assignments[0].get("definition") or {})
        if isinstance(first_def, dict):
            first_sample = {
                "keys":                sorted(list(first_def.keys()))[:30],
                "displayName":         first_def.get("displayName") or first_def.get("name"),
                "policyType":          first_def.get("policyType"),
                "has_policyRule":      isinstance(first_def.get("policyRule"), dict),
                "has_properties":      isinstance(first_def.get("properties"), dict),
                "properties_keys":     (
                    sorted(list((first_def.get("properties") or {}).keys()))[:20]
                    if isinstance(first_def.get("properties"), dict) else []
                ),
                "from_initiative":     assignments[0].get("from_initiative"),
            }
    diagnostics = {
        "raw_assignment_count":      len(assignments),
        "extra_blocking_def_count":  len(extra_blocking),
        "extra_used":                extra_used,
        "fetch_path":                _LAST_FETCH_PATH,
        "graph_last_error":          _GRAPH_LAST_ERROR,
        "effects_raw":               sorted(seen_effects_raw),
        "effects_resolved":          sorted(seen_effects_resolved),
        "modify_target_types":       sorted(set(modify_targets)),
        "definition_shapes":         sorted(seen_def_shapes),
        "first_definition":          first_sample,
    }

    return {
        "required_tags":     required_tags,
        "tag_defaults":      tag_defaults,
        "allowed_locations": allowed_locations,
        "manual_review":     manual_review,
        "field_operations":  field_operations,
        "subscription_id":   subscription_id,
        "diagnostics":       diagnostics,
    }


def clear_cache(subscription_id: Optional[str] = None) -> None:
    with _LOCK:
        if subscription_id:
            _CACHE.pop(subscription_id, None)
        else:
            _CACHE.clear()
