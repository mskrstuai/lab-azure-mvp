"""Thin wrappers around the official AWS & Azure pricing / catalog APIs.

Design invariant for this module: **no service-specific rules**.  The LLM
mapping agent drives everything via tool calls; this file only:

1. Knows how to talk to the two public APIs (one function each).
2. Compacts the response shape into something cheap to feed back to the
   LLM (we strip fields the model doesn't need, and cap list sizes).
3. Holds one small helper (AWS region-code → Pricing-API "location" human
   name) because the Pricing API literally won't accept ``ap-northeast-2``.

If you find yourself about to hard-code "Virtual Machines → use filter X",
stop — the LLM is supposed to discover that by composing these tools.
"""

from __future__ import annotations

import json as _json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

HOURS_PER_MONTH = 730.0
_AZURE_PRICES_BASE = "https://prices.azure.com/api/retail/prices"
_DEFAULT_TIMEOUT = 15.0


@dataclass
class PriceInfo:
    """Kept around because migration_agent/frontend still reference this shape.

    Populated either by the LLM (via the structured-output schema) or by
    callers that want a pre-baked None placeholder.
    """

    monthly_usd: Optional[float] = None
    hourly_usd: Optional[float] = None
    unit_price_usd: Optional[float] = None
    unit: Optional[str] = None
    sku_resolved: Optional[str] = None
    meter: Optional[str] = None
    region: Optional[str] = None
    currency: str = "USD"
    source: Optional[str] = None
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    assumptions: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# AWS region-code → Pricing-API "location" human name.
# The Pricing API rejects ``ap-northeast-2`` but accepts
# ``Asia Pacific (Seoul)``.  We expose this mapping to the LLM as part of
# the tool description so it can translate on its own.
# ---------------------------------------------------------------------------
AWS_REGION_TO_LOCATION: Dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "eu-south-1": "EU (Milan)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "me-south-1": "Middle East (Bahrain)",
    "af-south-1": "Africa (Cape Town)",
}


def aws_region_to_location(region: str) -> Optional[str]:
    if not region:
        return None
    return AWS_REGION_TO_LOCATION.get(region) or AWS_REGION_TO_LOCATION.get(region.lower())


# ---------------------------------------------------------------------------
# Azure Retail Prices API (public, no auth).
# ---------------------------------------------------------------------------
# Fields we ship back to the model.  The raw API response has ~40 fields per
# item; 90% are useless to the LLM and waste tokens.
_AZURE_ITEM_FIELDS = (
    "armRegionName",
    "armSkuName",
    "skuName",
    "productName",
    "meterName",
    "serviceName",
    "serviceFamily",
    "retailPrice",
    "unitOfMeasure",
    "unitPrice",
    "priceType",
    "currencyCode",
    "effectiveStartDate",
)


def _trim_azure_item(it: Dict[str, Any]) -> Dict[str, Any]:
    return {k: it.get(k) for k in _AZURE_ITEM_FIELDS if it.get(k) not in (None, "")}


def azure_retail_query(
    filter_expr: str,
    *,
    top: int = 50,
    max_items: int = 200,
) -> Dict[str, Any]:
    """Run one filtered call against the Azure Retail Prices API.

    Follows ``NextPageLink`` up to ``max_items`` rows so the LLM can see the
    full relevant slice even if the API wants to paginate (Virtual Machines
    in a region easily exceeds 100).
    """
    params = {"$filter": filter_expr, "$top": max(1, min(top, 100))}
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = None
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            while True:
                r = client.get(next_url) if next_url else client.get(
                    _AZURE_PRICES_BASE, params=params
                )
                r.raise_for_status()
                data = r.json()
                for it in data.get("Items") or []:
                    items.append(_trim_azure_item(it))
                    if len(items) >= max_items:
                        break
                next_url = data.get("NextPageLink")
                if not next_url or len(items) >= max_items:
                    break
    except Exception as e:  # pragma: no cover — surfaced to the LLM as text
        logger.warning("Azure retail query failed (%s): %s", filter_expr, e)
        return {
            "ok": False,
            "error": str(e),
            "filter": filter_expr,
            "items": [],
            "count": 0,
            "as_of": as_of,
            "source": "azure-retail-prices",
        }
    return {
        "ok": True,
        "filter": filter_expr,
        "items": items,
        "count": len(items),
        "truncated": len(items) >= max_items,
        "as_of": as_of,
        "source": "azure-retail-prices",
        "source_url": _AZURE_PRICES_BASE,
    }


# ---------------------------------------------------------------------------
# AWS Pricing API (boto3, must hit ``us-east-1``).
# ---------------------------------------------------------------------------
_aws_pricing_client = None


def _get_aws_pricing_client():
    global _aws_pricing_client
    if _aws_pricing_client is not None:
        return _aws_pricing_client
    try:
        import boto3
    except Exception as e:
        logger.warning("boto3 not installed: AWS pricing disabled (%s)", e)
        return None
    try:
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if access_key and secret_key:
            _aws_pricing_client = boto3.client(
                "pricing",
                region_name="us-east-1",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token or None,
            )
        else:
            profile = os.environ.get("AWS_PROFILE")
            session = boto3.Session(profile_name=profile) if profile else boto3.Session()
            _aws_pricing_client = session.client("pricing", region_name="us-east-1")
    except Exception as e:
        logger.warning("Could not initialise boto3 pricing client: %s", e)
        _aws_pricing_client = None
    return _aws_pricing_client


def _flatten_aws_product(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse one Pricing-API product into a compact, LLM-friendly row.

    Raw Pricing-API products are ~1-2 KB each with nested ``terms`` +
    ``product.attributes``.  We pull the attributes (vCPU, memory, ...) and
    a single on-demand USD price/unit so the LLM can spec-compare without
    re-parsing giant blobs.
    """
    attrs = (raw.get("product") or {}).get("attributes") or {}
    # Keep a curated, spec-relevant attribute subset.  The full set has
    # ~50 fields per EC2 product which burns tokens for nothing.
    keep = {
        "instanceType", "instanceFamily", "vcpu", "memory", "storage",
        "networkPerformance", "clockSpeed", "physicalProcessor",
        "currentGeneration", "processorArchitecture", "operatingSystem",
        "tenancy", "preInstalledSw", "capacitystatus", "licenseModel",
        "location", "regionCode",
        # RDS
        "databaseEngine", "databaseEdition", "deploymentOption", "engineCode",
        # EBS / disks
        "volumeApiName", "volumeType", "maxIopsvolume", "maxThroughputvolume",
        "maxVolumeSize",
        # S3
        "storageClass", "volumeType",
        # ElastiCache
        "cacheEngine",
        # ELB / others
        "productFamily", "groupDescription", "usagetype",
    }
    compact_attrs = {k: v for k, v in attrs.items() if k in keep}

    # Pull the first USD on-demand dimension.  Pricing API shape:
    # terms.OnDemand[TermId].priceDimensions[RateCode].{pricePerUnit.USD, unit, description}
    price_usd = None
    unit = None
    description = None
    try:
        terms = (raw.get("terms") or {}).get("OnDemand") or {}
        for term in terms.values():
            pdims = term.get("priceDimensions") or {}
            for pd in pdims.values():
                usd = (pd.get("pricePerUnit") or {}).get("USD")
                if usd is None:
                    continue
                try:
                    val = float(usd)
                except (TypeError, ValueError):
                    continue
                if val <= 0:
                    continue
                price_usd = val
                unit = pd.get("unit")
                description = pd.get("description")
                break
            if price_usd is not None:
                break
    except Exception:
        pass

    return {
        "sku": raw.get("product", {}).get("sku"),
        "product_family": (raw.get("product") or {}).get("productFamily"),
        "attributes": compact_attrs,
        "on_demand_usd": price_usd,
        "unit": unit,
        "description": description,
    }


def aws_pricing_query(
    service_code: str,
    filters: List[Dict[str, str]],
    *,
    max_results: int = 20,
) -> Dict[str, Any]:
    """One call to ``pricing.get_products`` with TERM_MATCH filters.

    ``filters`` is a list of ``{"field": "...", "value": "..."}`` objects;
    the LLM builds these from its prompt-time knowledge of AWS Pricing-API
    schema (we don't gate what fields it can use).
    """
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    client = _get_aws_pricing_client()
    if client is None:
        return {
            "ok": False,
            "error": "AWS Pricing client unavailable (boto3 missing or no credentials)",
            "service_code": service_code,
            "filters": filters,
            "items": [],
            "count": 0,
            "as_of": as_of,
            "source": "aws-pricing-api",
        }

    aws_filters = []
    for f in filters or []:
        field = f.get("field") or f.get("Field")
        value = f.get("value") or f.get("Value")
        if not field or value is None:
            continue
        aws_filters.append({"Type": "TERM_MATCH", "Field": field, "Value": str(value)})

    try:
        resp = client.get_products(
            ServiceCode=service_code,
            Filters=aws_filters,
            MaxResults=max(1, min(int(max_results), 100)),
        )
    except Exception as e:
        logger.warning("AWS pricing query failed (%s): %s", service_code, e)
        return {
            "ok": False,
            "error": str(e),
            "service_code": service_code,
            "filters": filters,
            "items": [],
            "count": 0,
            "as_of": as_of,
            "source": "aws-pricing-api",
        }

    items: List[Dict[str, Any]] = []
    for raw in resp.get("PriceList", []) or []:
        try:
            doc = raw if isinstance(raw, dict) else _json.loads(raw)
        except Exception:
            continue
        items.append(_flatten_aws_product(doc))

    return {
        "ok": True,
        "service_code": service_code,
        "filters": filters,
        "items": items,
        "count": len(items),
        "next_token": resp.get("NextToken"),
        "as_of": as_of,
        "source": "aws-pricing-api",
        "source_url": "https://aws.amazon.com/pricing/",
    }
