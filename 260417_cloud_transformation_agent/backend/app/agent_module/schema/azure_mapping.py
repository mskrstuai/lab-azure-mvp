"""Structured output for per-resource AWS → Azure target mapping.

This shape is what the LLM mapping agent emits for every AWS resource.  It
now bakes BOTH the service/SKU decision AND the priced result from its
research tools (`aws_pricing_query`, `azure_retail_query`) into a single
structured row, so the UI can show "service + monthly cost" without a
second round-trip.
"""

from typing import Any

from pydantic import BaseModel, Field


class SpecSummary(BaseModel):
    """Lightweight spec snapshot pulled from Pricing APIs.

    Only the dimensions the UI (and a human migration architect) actually
    use to judge equivalence.  Everything optional — smaller services like
    S3/Lambda have no vCPU/memory at all.
    """

    vcpu: str | None = Field(
        default=None,
        description="Number of vCPUs as a string (some catalogs report '0.25').",
    )
    memory_gb: str | None = Field(
        default=None, description="RAM in GB, as a string (e.g. '4', '16 GB')."
    )
    storage: str | None = Field(
        default=None,
        description=(
            "Storage/volume size or tier (e.g. 'EBS only', '128 GB SSD', 'P10', 'S30')."
        ),
    )
    network: str | None = Field(
        default=None,
        description="Network performance class if relevant (e.g. 'Up to 5 Gbps').",
    )
    engine: str | None = Field(
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

    monthly_usd: float | None = Field(
        default=None,
        description=(
            "Estimated monthly cost in USD based on on-demand pricing × 730 h/mo. "
            "Leave null for usage-based services (Functions, Log Analytics, "
            "Cosmos serverless, Standard LB, ...) and explain in `note`."
        ),
    )
    hourly_usd: float | None = Field(
        default=None, description="On-demand hourly USD if the meter is per-hour."
    )
    unit_price_usd: float | None = Field(
        default=None,
        description="Raw price per `unit` exactly as the API returned it.",
    )
    unit: str | None = Field(
        default=None,
        description="Unit string from the source API (e.g. 'Hrs', '1 GB/Month').",
    )
    sku_resolved: str | None = Field(
        default=None,
        description=(
            "The concrete SKU you actually priced — prefer Terraform-valid names "
            "(e.g. `Standard_D2s_v5`, `B_Standard_B1ms`, `Premium_LRS`)."
        ),
    )
    meter: str | None = Field(
        default=None, description="The Retail API meter name (or AWS usage dimension)."
    )
    region: str | None = Field(default=None)
    currency: str = "USD"
    source: str | None = Field(
        default=None,
        description="'azure-retail-prices' or 'aws-pricing-api'.",
    )
    source_url: str | None = Field(default=None)
    as_of: str | None = Field(
        default=None,
        description="ISO-8601 timestamp copied from the tool response.",
    )
    assumptions: str | None = Field(
        default=None,
        description=(
            "One sentence describing the pricing assumption (e.g. 'Linux on-demand "
            "× 730 h', 'Blob Hot per-GB/mo, transactions excluded')."
        ),
    )
    note: str | None = Field(
        default=None,
        description=(
            "Anything worth flagging: 'usage-based — no fixed monthly', "
            "'requested t3.medium unavailable, used t3a.medium', etc."
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

    monthly_delta_usd: float | None = Field(
        default=None,
        description=(
            "Azure monthly − AWS monthly, in USD.  Should be ≤ 0 when both are "
            "priced and the constraint applies.  Null when either side is "
            "usage-based or unpriced."
        ),
    )

    rationale: str = Field(
        description=(
            "One sentence (≤ 40 words): **why the Azure target matches AWS on "
            "spec** (capacity/engine/tier). Mention price only briefly if "
            "helpful (e.g. Azure at or below AWS monthly)."
        )
    )
    caveats: str = Field(
        default="",
        description=(
            "Optional ≤ 1 sentence on gaps: engine-version mismatch, "
            "HA trade-offs, data-migration hazards, etc."
        ),
    )


class AzureTargetMappingList(BaseModel):
    mappings: list[AzureTargetMapping] = Field(
        default_factory=list,
        description="One entry per input AWS resource, in the SAME order as the input.",
    )
