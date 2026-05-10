"""Structured output for per-resource AWS → Azure target mapping.

This shape is what the LLM mapping agent emits for every AWS resource.  It
now bakes BOTH the service/SKU decision AND the priced result from its
research tools (`aws_pricing_query`, `azure_retail_query`) into a single
structured row, so the UI can show "service + monthly cost" without a
second round-trip.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SpecSummary(BaseModel):
    """Lightweight spec snapshot pulled from Pricing APIs.

    Only the dimensions the UI (and a human migration architect) actually
    use to judge equivalence.  Everything optional — smaller services like
    S3/Lambda have no vCPU/memory at all.
    """

    vcpu: Optional[str] = Field(
        default=None,
        description="Number of vCPUs as a string (some catalogs report '0.25').",
    )
    memory_gb: Optional[str] = Field(
        default=None, description="RAM in GB, as a string (e.g. '4', '16 GB')."
    )
    storage: Optional[str] = Field(
        default=None,
        description=(
            "Storage/volume size or tier (e.g. 'EBS only', '128 GB SSD', 'P10', 'S30')."
        ),
    )
    network: Optional[str] = Field(
        default=None,
        description="Network performance class if relevant (e.g. 'Up to 5 Gbps').",
    )
    engine: Optional[str] = Field(
        default=None,
        description="DB engine / cache engine / OS if the service cares (e.g. 'MySQL 8', 'Redis 7', 'Linux').",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Any other spec bits worth showing but not captured above. "
            "Values may be strings, numbers, or booleans — whatever the "
            "Pricing API returned."
        ),
    )


class PriceInfo(BaseModel):
    """One priced row fetched via a Pricing API tool."""

    monthly_usd: Optional[float] = Field(
        default=None,
        description=(
            "Estimated monthly cost in USD based on on-demand pricing × 730 h/mo. "
            "Leave null for usage-based services (Functions, Log Analytics, "
            "Cosmos serverless, Standard LB, ...) and explain in `note`."
        ),
    )
    monthly_1yr_ri_usd: Optional[float] = Field(
        default=None,
        description=(
            "1-year Reserved Instance monthly cost (USD). Computed from the total "
            "reservation `retailPrice` divided by 12. Null when the SKU does not "
            "offer reservations or is usage-based."
        ),
    )
    monthly_3yr_ri_usd: Optional[float] = Field(
        default=None,
        description=(
            "3-year Reserved Instance monthly cost (USD). Computed from the total "
            "reservation `retailPrice` divided by 36."
        ),
    )
    hourly_usd: Optional[float] = Field(
        default=None, description="On-demand hourly USD if the meter is per-hour."
    )
    unit_price_usd: Optional[float] = Field(
        default=None,
        description="Raw price per `unit` exactly as the API returned it.",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit string from the source API (e.g. 'Hrs', '1 GB/Month').",
    )
    sku_resolved: Optional[str] = Field(
        default=None,
        description=(
            "The concrete SKU you actually priced — prefer Terraform-valid names "
            "(e.g. `Standard_D2s_v5`, `B_Standard_B1ms`, `Premium_LRS`)."
        ),
    )
    meter: Optional[str] = Field(
        default=None, description="The Retail API meter name (or AWS usage dimension)."
    )
    region: Optional[str] = Field(default=None)
    currency: str = "USD"
    source: Optional[str] = Field(
        default=None,
        description="'azure-retail-prices' or 'aws-pricing-api'.",
    )
    source_url: Optional[str] = Field(default=None)
    as_of: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp copied from the tool response.",
    )
    assumptions: Optional[str] = Field(
        default=None,
        description=(
            "One sentence describing the pricing assumption — **write in Korean**. "
            "Example meaning: Linux on-demand × 730 h, Blob Hot per-GB/mo excluding transactions."
        ),
    )
    note: Optional[str] = Field(
        default=None,
        description=(
            "Flags worth calling out — **write in Korean** (e.g. usage-based no fixed monthly, "
            "or substitute SKU if requested class unavailable)."
        ),
    )


class CostInsight(BaseModel):
    """Per-resource cost-savings narrative for the user.

    Computed AFTER both ``aws_price`` and ``azure_price`` are filled in.
    Surfaces the savings story in a way the UI can highlight without
    re-deriving from raw numbers.
    """

    savings_pct: Optional[float] = Field(
        default=None,
        description=(
            "Savings percentage — (aws_monthly − azure_monthly) / aws_monthly × 100, "
            "rounded to 1 decimal. Positive = Azure cheaper. Null when either side "
            "is usage-based or otherwise un-priced."
        ),
    )
    monthly_savings_usd: Optional[float] = Field(
        default=None,
        description=(
            "Monthly savings in USD — aws_monthly − azure_monthly. "
            "Positive = Azure cheaper. Null when not comparable."
        ),
    )
    annual_savings_usd: Optional[float] = Field(
        default=None,
        description=(
            "Annual savings in USD — monthly_savings × 12. "
            "Positive = Azure cheaper. Null when not comparable."
        ),
    )
    headline: str = Field(
        default="",
        description=(
            "Korean one-liner shown to the user — write naturally:\n"
            "  • savings: '월 32% 절감 · 연 $540 절감'\n"
            "  • neutral: 'AWS와 비슷한 가격대'\n"
            "  • premium: '월 $15 더 비쌈 (12% 추가)'\n"
            "  • usage-based: '종량제 — 실 사용량에 비례'"
        ),
    )
    category: str = Field(
        default="neutral",
        description=(
            "One of:\n"
            "  • 'savings'     — Azure ≥ 5% cheaper\n"
            "  • 'neutral'     — within ±5%\n"
            "  • 'premium'     — Azure ≥ 5% more expensive\n"
            "  • 'usage-based' — at least one side has no flat monthly\n"
            "  • 'free'        — both sides are zero (network/IAM components)"
        ),
    )


class AzureTargetMapping(BaseModel):
    """One row: a single AWS resource → Azure target, priced on both sides."""

    aws_key: str = Field(
        description=(
            "Stable key echoed back from the request so the UI can join the "
            "row back to the source AWS resource. Prefer ARN when available."
        )
    )
    aws_service: str = Field(description="Original AWS service label (e.g. 'EC2').")
    aws_type: str = Field(
        default="",
        description="Original AWS resource type / class (e.g. 'Instance', 'Bucket').",
    )
    aws_name: str = Field(
        default="",
        description="Display name of the AWS resource (tag Name or identifier).",
    )
    aws_sku_hint: str = Field(
        default="",
        description=(
            "The concrete AWS SKU / class you chose for pricing lookup — "
            "e.g. 't3.medium', 'db.t3.medium', 'gp3', 'cache.t3.micro'. "
            "Empty only for resources with no SKU (IAM, SG, routes)."
        ),
    )
    aws_spec: SpecSummary = Field(
        default_factory=SpecSummary,
        description="Spec snapshot pulled from `aws_pricing_query` — vCPU, RAM, etc.",
    )
    aws_price: PriceInfo = Field(
        default_factory=PriceInfo,
        description="AWS on-demand monthly cost from `aws_pricing_query`.",
    )

    azure_service: str = Field(
        description=(
            "Primary Azure service the resource should map to, e.g. "
            "'Azure Virtual Machines', 'Azure Database for PostgreSQL - Flexible Server'."
        )
    )
    azure_resource_type: str = Field(
        default="",
        description=(
            "Specific azurerm Terraform resource type (snake_case) that "
            "implements the target, e.g. 'azurerm_linux_virtual_machine'."
        ),
    )
    azure_sku_suggestion: str = Field(
        default="",
        description=(
            "The Terraform-valid Azure SKU chosen for **spec parity** with AWS "
            "(vCPU/RAM/engine/tier), not for price similarity. "
            "When both sides have `monthly_usd`, Azure must be **≤ AWS**; among "
            "spec-valid options meeting that, prefer lower Azure cost."
        ),
    )
    azure_spec: SpecSummary = Field(
        default_factory=SpecSummary,
        description="Spec snapshot pulled from `azure_retail_query` for the chosen SKU.",
    )
    azure_price: PriceInfo = Field(
        default_factory=PriceInfo,
        description="Azure on-demand monthly cost from `azure_retail_query`.",
    )

    monthly_delta_usd: Optional[float] = Field(
        default=None,
        description=(
            "Azure monthly − AWS monthly, in USD.  Should be ≤ 0 when both are "
            "priced and the constraint applies.  Null when either side is "
            "usage-based or unpriced."
        ),
    )

    cost_insight: CostInsight = Field(
        default_factory=CostInsight,
        description=(
            "User-facing cost-savings summary. MUST be filled whenever both "
            "monthly prices are available."
        ),
    )

    rationale: str = Field(
        description=(
            "One sentence (≤ 40 words), **in Korean**: **why the Azure target matches AWS on "
            "spec** (capacity/engine/tier). Mention price only briefly if helpful "
            "(e.g. Azure monthly at or below AWS)."
        )
    )
    caveats: str = Field(
        default="",
        description=(
            "Optional ≤ 1 sentence, **in Korean**: gaps such as engine-version mismatch, "
            "HA trade-offs, data-migration risks, etc."
        ),
    )
    cost_tips: list[str] = Field(
        default_factory=list,
        description=(
            "Optional list of Korean one-liners suggesting further cost optimizations:\n"
            "  • 'Burstable B-series 사용 시 월 50%+ 절감 가능 (비핵심 워크로드)'\n"
            "  • 'Storage Cool tier 변경 시 월 50% 절감 (접근 빈도 낮을 때)'\n"
            "  • 'Windows Server 라이선스 보유 시 Hybrid Benefit으로 추가 40% 절감'\n"
            "  • 'Reserved Instance 3년 약정 시 추가 60% 절감'\n"
            "Each tip should be standalone and actionable."
        ),
    )


class AzureTargetMappingList(BaseModel):
    mappings: list[AzureTargetMapping] = Field(
        default_factory=list,
        description="One entry per input AWS resource, in the SAME order as the input.",
    )
