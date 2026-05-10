"""OpenAI-format tool definitions the mapping agent uses for pricing research.

Keep the tool descriptions long & instructional — the LLM uses these as its
only manual for the underlying APIs.  Every field the model is allowed to
filter on must be explained here; otherwise it will guess and produce 400s.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from threading import Lock
from typing import Any, Dict, List, Tuple

from app.services.pricing import (
    AWS_REGION_TO_LOCATION,
    aws_pricing_query,
    azure_retail_query,
)
from app.services.azure_policy import policies_for_resource_type

logger = logging.getLogger(__name__)

# ── In-memory pricing cache ────────────────────────────────────────
# AWS Pricing API and Azure Retail Prices change infrequently (hours/days),
# so caching the same filter→response saves real seconds on repeat queries
# both within a single mapping run AND across runs while the server is up.
_PRICE_CACHE: Dict[str, Tuple[float, str]] = {}
_CACHE_LOCK = Lock()
_CACHE_TTL = float(os.getenv("PRICING_CACHE_TTL", "3600"))   # 1 hour default
_CACHE_HITS = 0
_CACHE_MISSES = 0


def _cache_key(name: str, args_json: str) -> str:
    """Stable cache key from tool name + sorted-key args JSON."""
    try:
        args = json.loads(args_json or "{}")
        normalized = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        normalized = args_json or ""
    return f"{name}::{normalized}"


def cache_stats() -> Dict[str, Any]:
    return {
        "size":   len(_PRICE_CACHE),
        "hits":   _CACHE_HITS,
        "misses": _CACHE_MISSES,
        "ttl_s":  _CACHE_TTL,
    }


def clear_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _PRICE_CACHE.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


# ---------------------------------------------------------------------------
# Region-name helper: a small, static table injected into the system prompt so
# the LLM doesn't have to guess how to translate 'ap-northeast-2' into the
# Pricing API's 'Asia Pacific (Seoul)'.
# ---------------------------------------------------------------------------
def aws_region_table_markdown() -> str:
    lines = ["| region | location |", "|---|---|"]
    for code, name in AWS_REGION_TO_LOCATION.items():
        lines.append(f"| `{code}` | `{name}` |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling shape).
# ---------------------------------------------------------------------------
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "azure_retail_query",
            "description": (
                "Query the Azure Retail Prices API (public, no auth).  Returns a list "
                "of price rows matching an OData `$filter` expression.  Use it to "
                "(1) enumerate available SKUs in a region so you can compare specs, "
                "(2) fetch the exact on-demand unit price for a specific SKU.\n\n"
                "Every row contains: armRegionName, armSkuName, skuName, productName, "
                "meterName, serviceName, retailPrice, unitOfMeasure (e.g. '1 Hour', "
                "'1 GB/Month'), priceType, currencyCode.\n\n"
                "Filter tips:\n"
                "- ALWAYS include `priceType eq 'Consumption'` (excludes Reservations / DevTest).\n"
                "- Anchor on `armRegionName eq '<region>'` (e.g. 'koreacentral', 'eastus').\n"
                "- Use `serviceName eq` for the service family.  Examples:\n"
                "    'Virtual Machines', 'Storage', 'Application Gateway', 'Load Balancer', "
                "'Azure Database for PostgreSQL', 'Azure Database for MySQL', 'Redis Cache', "
                "'Virtual Network', 'Azure Kubernetes Service', 'Azure Cosmos DB'.\n"
                "- Narrow by `armSkuName eq '<SKU>'` when you know the exact SKU.\n"
                "- Use `contains(productName, 'Flexible Server')` etc. to exclude legacy products.\n"
                "- Use `contains(meterName, 'vCore')` / `contains(meterName, 'Data Stored')` to "
                "pick the right meter when a SKU has several.\n"
                "- Response is paginated; you get up to `max_items` rows aggregated here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_expr": {
                        "type": "string",
                        "description": "OData `$filter` expression (see examples in the tool description).",
                    },
                    "top": {
                        "type": "integer",
                        "description": "Page size, 1–100.  50 is a good default.",
                        "default": 50,
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Cap on aggregated items across pagination.  Keep ≤ 200.",
                        "default": 100,
                    },
                },
                "required": ["filter_expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aws_pricing_query",
            "description": (
                "Query the AWS Pricing API (boto3, us-east-1 endpoint; requires the same "
                "AWS credentials the scanner uses).  Returns normalised product rows: "
                "each row has a compacted `attributes` dict (vcpu, memory, storage, "
                "instanceType, operatingSystem, tenancy, ...) AND the on-demand USD "
                "hourly/unit price (`on_demand_usd` + `unit`).\n\n"
                "Common `service_code` values: 'AmazonEC2', 'AmazonRDS', 'AmazonS3', "
                "'AmazonElastiCache', 'AmazonDynamoDB', 'AWSELB', 'AmazonECS', "
                "'AmazonEKS', 'AWSLambda'.\n\n"
                "`filters` is a list of `{field, value}` pairs (all combined with AND).  "
                "Useful `field` names by service:\n"
                "- EC2:   instanceType, location, operatingSystem, tenancy, preInstalledSw, "
                "capacitystatus, productFamily ('Compute Instance' / 'Storage').\n"
                "- EBS:   volumeApiName ('gp3'/'gp2'/'io2'/'st1'/'sc1'), location, productFamily='Storage'.\n"
                "- RDS:   instanceType, location, databaseEngine ('MySQL'/'PostgreSQL'/'Aurora'), "
                "deploymentOption ('Single-AZ'/'Multi-AZ'), licenseModel.\n"
                "- S3:    location, productFamily='Storage', storageClass ('General Purpose').\n"
                "- ElastiCache: instanceType, cacheEngine ('Redis'/'Memcached'), location.\n"
                "- ELB:   location, productFamily='Load Balancer', usagetype.\n\n"
                "`location` must be the human-readable form (e.g. 'Asia Pacific (Seoul)'), "
                "NOT the region code.  Use the mapping table in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_code": {
                        "type": "string",
                        "description": "AWS service code, e.g. 'AmazonEC2'.",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["field", "value"],
                        },
                        "description": "TERM_MATCH filters combined with AND.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "1–100.  10-20 is usually enough for spec comparisons.",
                        "default": 10,
                    },
                },
                "required": ["service_code", "filters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "azure_query",
            "description": (
                "Run a **read-only** Azure CLI command (any resource type).  "
                "Returns parsed JSON in the `data` field.  Always default JSON "
                "output — never use `--output table`.\n\n"
                "⚠ **VERY IMPORTANT — narrow the result with `--query`:**\n"
                "  Raw `vm list-skus` returns hundreds of SKUs each with a verbose "
                "`capabilities` array.  Without `--query` the result is trimmed "
                "(field projection + item cap) and you may miss the SKU you wanted.  "
                "Always project to just the fields you need:\n\n"
                "  ✓ Available B-family in koreacentral:\n"
                "    ['vm','list-skus','--location','koreacentral',\n"
                "     '--resource-type','virtualMachines','--size','Standard_B',\n"
                "     '--query','[?length(restrictions || `[]`)==`0`].{name:name,family:family}']\n\n"
                "  ✓ Specific SKU availability check:\n"
                "    ['vm','list-skus','--location','koreacentral',\n"
                "     '--query',\"[?name=='Standard_B2as_v2'].{name:name,restrictions:restrictions}\"]\n\n"
                "  ✓ Storage SKUs available:\n"
                "    ['storage','account','list-skus','--location','koreacentral',\n"
                "     '--query','[].{name:name,tier:tier,kind:kind}']\n\n"
                "  ✓ Soft-delete check for a name:\n"
                "    ['storage','account','list-deleted','--location','koreacentral',\n"
                "     '--query',\"[?name=='myaccount']\"]\n\n"
                "  ✓ Network usage / quota:\n"
                "    ['network','list-usages','--location','koreacentral',\n"
                "     '--query','[?currentValue>=`limit`]']\n\n"
                "If the response sets `data_truncated: true`, narrow the query "
                "and call again.  Write verbs (create/delete/update/set/...) "
                "are blocked at the validator."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Arguments after 'az'. Example: ['vm','list-skus','--location','koreacentral'].",
                    },
                },
                "required": ["args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "azure_policies_for_type",
            "description": (
                "Return Azure Policy assignments that constrain a SPECIFIC resource "
                "type in the target subscription, plus any 'universal' policies "
                "(those without a type filter — typically tag/location requirements).\n\n"
                "Returns a compact list — display name, effect (deny/audit/modify/...), "
                "one-line rule summary, and the assignment's parameter values — so it "
                "fits in the LLM context without dumping full policy JSON.  Call this "
                "for each Azure type you generate (VM, storage account, vnet, etc.) "
                "to ensure the code complies (correct tags, allowed location, allowed "
                "SKU values).\n\n"
                "Don't call without an azure_type.  If you need ALL policies use a "
                "wildcard type like 'Microsoft.Resources/subscriptions' — but that's "
                "usually wrong; prefer per-type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Target Azure subscription ID (UUID).",
                    },
                    "azure_type": {
                        "type": "string",
                        "description": (
                            "Full Azure resource type, e.g. "
                            "'Microsoft.Compute/virtualMachines', "
                            "'Microsoft.Storage/storageAccounts', "
                            "'Microsoft.Network/virtualNetworks'."
                        ),
                    },
                },
                "required": ["subscription_id", "azure_type"],
            },
        },
    },
]


# ── az CLI safety: blocked write verbs (mirrors fix_agent_tools._validate_az_args) ──
_AZ_BLOCKED = {
    "create", "delete", "update", "set", "deallocate", "restart",
    "start", "stop", "regenerate", "purge", "lock", "unlock",
    "add", "remove", "redeploy", "reimage",
    "config", "import", "configure", "login", "logout",
}


def _validate_az_args(args: List[str]) -> str | None:
    if not args:
        return "args is empty"
    for tok in args:
        if tok.startswith("-"):
            break
        if tok in _AZ_BLOCKED:
            return f"Write operation '{tok}' not allowed — only read-only az commands"
    return None


def _trim_az_data(data: Any, max_bytes: int = 11000) -> Any:
    """Smartly shrink large `data` payloads from `az` so they survive the
    LLM context cap without garbled JSON.

    Strategy for list-of-dicts (typical for ``vm list-skus`` / ``list-deleted``):
      1. If the full thing fits in ``max_bytes``, return as-is.
      2. Otherwise project each dict to common useful keys and re-check.
      3. If still too big, cap the item count and append a sentinel.
    """
    if not isinstance(data, list):
        return data
    if json_len(data) <= max_bytes:
        return data
    # Step 2: project to known-useful keys
    if all(isinstance(d, dict) for d in data):
        keep = {
            # generic
            "name", "id", "kind", "type", "displayName", "value",
            # SKU / capacity
            "family", "tier", "size", "resourceType", "locations", "restrictions",
            "skuName", "armSkuName", "apiVersions", "capabilities",
            # quota / usage
            "currentValue", "limit", "unit",
            # storage / network specific
            "deletedRetentionPolicy", "creationTime", "deletionTime", "location",
        }
        slim = [{k: v for k, v in d.items() if k in keep} for d in data]
        if json_len(slim) <= max_bytes:
            return slim
        # Step 3: also cap count
        per_item = max(80, json_len(slim) // max(1, len(slim)))
        max_items = max(20, max_bytes // per_item)
        return slim[:max_items] + [{
            "_truncated": True,
            "_total":     len(slim),
            "_kept":      max_items,
            "_hint":      "결과가 잘렸습니다 — `--query` 플래그로 범위를 좁히세요 (예: \"[?length(restrictions||\\`[]\\`)==\\`0\\`].name\")",
        }]
    # Plain list — just truncate
    return data[:60] + [{"_truncated": True, "_total": len(data)}]


def json_len(obj: Any) -> int:
    """Length of obj when serialized to JSON (used by _trim_az_data)."""
    try:
        return len(json.dumps(obj, default=str))
    except Exception:
        return 0


def _run_az_readonly(args: List[str]) -> Dict[str, Any]:
    err = _validate_az_args(args)
    if err:
        logger.warning("azure_query rejected: %s (args=%s)", err, args)
        return {"ok": False, "error": err}
    cmd = ["az"] + list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("azure_query timeout: %s", " ".join(cmd))
        return {"ok": False, "error": "az command timed out after 120s", "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"ok": False, "error": "az binary not found on host"}
    out = (proc.stdout or "").strip()
    err_out = (proc.stderr or "").strip()
    parsed: Any = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = out  # leave as string
    # Trim large list payloads BEFORE the dispatcher's blunt 14000-char cap
    # would chop the JSON mid-string and break the LLM's parsing.
    trimmed = _trim_az_data(parsed)
    truncated = trimmed is not parsed and isinstance(parsed, list)
    count = len(parsed) if isinstance(parsed, list) else None
    logger.info(
        "azure_query rc=%s items=%s trimmed=%s :: %s",
        proc.returncode, count, truncated, " ".join(cmd),
    )
    return {
        "ok": proc.returncode == 0,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "data": trimmed,
        "data_truncated": truncated,
        "data_total":     count,
        "stderr": err_out[-800:] if err_out else "",
    }


# ---------------------------------------------------------------------------
# Dispatcher — the mapping agent's tool loop calls this for every tool_call.
# ---------------------------------------------------------------------------
def execute_tool_call(name: str, arguments_json: str) -> str:
    """Dispatch a single tool call and return a JSON string for the model.

    We never raise: every failure becomes a JSON blob with ``ok=False`` and
    an ``error`` field so the LLM can decide to retry / adjust its filter.
    We also hard-cap the response size so one unlucky query (e.g. 2000 VM
    SKUs) doesn't blow up the chat context.

    Results are cached in-memory keyed on (tool name, normalized args) for
    ``PRICING_CACHE_TTL`` seconds — pricing data rarely changes within an
    hour, and many resources hit the exact same filter.
    """
    global _CACHE_HITS, _CACHE_MISSES

    try:
        args: Dict[str, Any] = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid tool arguments JSON: {e}"})

    # ── Cache lookup ──────────────────────────────────────────────
    key = _cache_key(name, arguments_json)
    now = time.time()
    with _CACHE_LOCK:
        cached = _PRICE_CACHE.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            _CACHE_HITS += 1
            return cached[1]
        _CACHE_MISSES += 1

    if name == "azure_retail_query":
        result = azure_retail_query(
            filter_expr=str(args.get("filter_expr") or args.get("filter") or ""),
            top=int(args.get("top") or 50),
            max_items=int(args.get("max_items") or 100),
        )
    elif name == "aws_pricing_query":
        result = aws_pricing_query(
            service_code=str(args.get("service_code") or ""),
            filters=list(args.get("filters") or []),
            max_results=int(args.get("max_results") or 10),
        )
    elif name == "azure_query":
        result = _run_az_readonly(list(args.get("args") or []))
    elif name == "azure_policies_for_type":
        sub_id    = str(args.get("subscription_id") or "").strip()
        az_type   = str(args.get("azure_type") or "").strip()
        if not sub_id or not az_type:
            result = {"ok": False, "error": "subscription_id and azure_type required"}
        else:
            try:
                policies = policies_for_resource_type(sub_id, az_type)
                result = {"ok": True, "azure_type": az_type, "count": len(policies), "policies": policies}
            except Exception as e:
                result = {"ok": False, "error": str(e)}
    else:
        result = {"ok": False, "error": f"Unknown tool '{name}'"}

    payload = json.dumps(result, default=str)
    # ~12K chars ≈ ~3K tokens — plenty for the LLM, bounded for the context window.
    cap = 14000
    if len(payload) > cap:
        # Trim the items list first — keep metadata so the model knows it was truncated.
        if isinstance(result, dict) and "items" in result:
            items = result.get("items") or []
            trimmed = items[: max(1, len(items) // 2)]
            result["items"] = trimmed
            result["truncated_by_agent"] = True
            result["original_count"] = len(items)
            payload = json.dumps(result, default=str)
        if len(payload) > cap:
            payload = payload[: cap - 200] + '..."<TRUNCATED>"}'

    # Save to cache for next time
    with _CACHE_LOCK:
        _PRICE_CACHE[key] = (now, payload)
    return payload
