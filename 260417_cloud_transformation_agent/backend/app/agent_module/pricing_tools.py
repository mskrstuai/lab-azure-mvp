"""OpenAI-format tool definitions the mapping agent uses for pricing research.

Keep the tool descriptions long & instructional — the LLM uses these as its
only manual for the underlying APIs.  Every field the model is allowed to
filter on must be explained here; otherwise it will guess and produce 400s.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.services.pricing import (
    AWS_REGION_TO_LOCATION,
    aws_pricing_query,
    azure_retail_query,
)

logger = logging.getLogger(__name__)


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
]


# ---------------------------------------------------------------------------
# Dispatcher — the mapping agent's tool loop calls this for every tool_call.
# ---------------------------------------------------------------------------
def execute_tool_call(name: str, arguments_json: str) -> str:
    """Dispatch a single tool call and return a JSON string for the model.

    We never raise: every failure becomes a JSON blob with ``ok=False`` and
    an ``error`` field so the LLM can decide to retry / adjust its filter.
    We also hard-cap the response size so one unlucky query (e.g. 2000 VM
    SKUs) doesn't blow up the chat context.
    """
    try:
        args: Dict[str, Any] = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid tool arguments JSON: {e}"})

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
    return payload
