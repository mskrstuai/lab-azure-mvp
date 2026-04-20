"""AWS → Azure per-resource mapping agent, tool-calling edition.

Design:
- We NEVER hard-code "which Azure SKU to price for which AWS type" in Python.
- The LLM drives the research: for each AWS resource it calls
  ``aws_pricing_query`` to confirm the AWS spec + price, ``azure_retail_query``
  to enumerate candidate Azure SKUs in the target region, compares vCPU /
  RAM / engine / storage tier, and only then returns a structured
  ``AzureTargetMapping`` with both sides fully priced.
- Resources are fanned out with a ``ThreadPoolExecutor`` — each resource is
  an independent conversation, so a 2-minute tail latency on one row can't
  block the others.

The siblings of this module have two patterns for Azure OpenAI initialisation
(API key vs Managed Identity vs DefaultAzureCredential) — we reuse the same
logic here so a deployment config that works for the planner also works for
the mapper.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from azure.identity import (
    DefaultAzureCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)
from openai import (
    APIConnectionError,
    APITimeoutError,
    AzureOpenAI,
    BadRequestError,
    RateLimitError,
)
from pydantic import ValidationError

from .pricing_tools import TOOLS, aws_region_table_markdown, execute_tool_call
from .schema.azure_mapping import AzureTargetMapping

# Transient failures we treat as worth one more shot on top of the SDK's
# built-in retries.  Everything else is re-raised untouched.
_RETRYABLE_EXC = (APIConnectionError, APITimeoutError, RateLimitError)


_SYSTEM_PROMPT_TEMPLATE = """\
You are a senior cloud-migration architect AND a pricing analyst.

For ONE AWS resource, your job is to:
  1. Identify the concrete AWS SKU / instance-class / storage-class.
     If the input already gives you the exact class (e.g. `t3.medium`,
     `db.t3.medium`, `gp3`), use it directly. Otherwise infer it from the
     resource type, tags, or name.
  2. Call `aws_pricing_query` to confirm the AWS spec (vCPU, RAM, ...) AND
     fetch the on-demand hourly price in the resource's source region.
  3. Decide the right Azure service family (use the mapping table below
     unless the resource's spec / tags clearly demand something else).
  4. Call `azure_retail_query` to enumerate candidate SKUs in the target
     Azure region and narrow down to the SINGLE best match **primarily from
     spec parity with AWS** (vCPU / RAM / storage tier / engine parity /
     burstable vs GP / redundancy class).  **Price similarity to AWS is NOT
     the selection criterion** — **similar spec/capacity is**.
  4b. **Price constraint vs AWS (mandatory when both sides are priced):**
     The Azure on-demand **monthly** you record **must not exceed** the AWS
     on-demand **monthly** for this resource (same comparison basis: compute
     meter vs compute meter, etc.).  In other words: **Azure monthly ≤ AWS
     monthly** whenever you have numeric `monthly_usd` on both sides.
     - First shortlist Azure SKUs that **match the AWS workload spec** well.
     - From that shortlist, **discard any SKU whose priced monthly is above
       the AWS monthly**; choose among the remainder.  If **no** spec-adequate
       SKU is ≤ AWS monthly, pick the **closest spec match** whose price is
       still ≤ AWS if any exists; if truly impossible, state clearly in
       `caveats` (do not silently pick a more expensive Azure SKU).
     - **Among** spec-good Azure options that satisfy **Azure ≤ AWS** monthly,
       you may prefer the **lower** Azure monthly cost (still spec-valid).
     - In `rationale`, lead with **why the spec matches AWS**; add one clause
       on price only if useful (e.g. "Azure monthly at or below AWS at this tier.").
  5. Call `azure_retail_query` once more to get the exact on-demand monthly
     price for the chosen SKU.  Use `730 h/mo` for hourly units.  For usage-
     based services (Lambda, Cosmos serverless, Standard LB, Functions,
     Log Analytics, Key Vault) leave `monthly_usd` null and explain in `note`.
  6. Return a SINGLE JSON object conforming to the `AzureTargetMapping`
     schema — no prose, no code fence.  Every pricing number MUST come
     from a tool response; NEVER invent a dollar amount.

Canonical AWS → Azure mappings (use these as the strong default):

- EC2 Instance                → `azurerm_linux_virtual_machine` / `_windows_virtual_machine`
- EC2 LaunchTemplate / ASG    → `azurerm_linux_virtual_machine_scale_set`
- EC2 EBS Volume              → `azurerm_managed_disk`
- EC2 Security Group          → `azurerm_network_security_group` (usually free)
- EC2 VPC / Subnet / Route    → `azurerm_virtual_network` / `_subnet` / `_route_table` (free)
- EC2 NAT Gateway             → `azurerm_nat_gateway`
- EC2 EIP                     → `azurerm_public_ip`
- RDS (Postgres)              → `azurerm_postgresql_flexible_server`
- RDS (MySQL/MariaDB)         → `azurerm_mysql_flexible_server`
- RDS (SQL Server)            → `azurerm_mssql_database` / `_mssql_managed_instance`
- RDS (Aurora)                → `azurerm_postgresql_flexible_server` / `_mysql_flexible_server` (note engine)
- S3 Bucket                   → `azurerm_storage_account`
- DynamoDB Table              → `azurerm_cosmosdb_account` (SQL API)
- ElastiCache Redis           → `azurerm_redis_cache`
- Lambda Function             → `azurerm_linux_function_app` (usage-based pricing)
- ECS/Fargate                 → `azurerm_container_app`  (heavy K8s → `_kubernetes_cluster`)
- EKS                         → `azurerm_kubernetes_cluster`
- Application LB              → `azurerm_application_gateway`
- Network LB / Classic        → `azurerm_lb`
- CloudFront                  → `azurerm_cdn_frontdoor_profile`
- Route 53                    → `azurerm_dns_zone`
- Secrets Manager / SSM PS    → `azurerm_key_vault`
- KMS                         → `azurerm_key_vault_key`
- IAM Role / Policy           → `azurerm_role_assignment` (free)
- SNS                         → `azurerm_eventgrid_topic` or Service Bus
- SQS                         → `azurerm_servicebus_queue`
- Kinesis / MSK               → `azurerm_eventhub_namespace`
- CloudWatch Logs             → `azurerm_log_analytics_workspace`
- EFS                         → `azurerm_storage_share`

AWS region-code → AWS Pricing-API `location` value (use these in your filters):

{aws_region_table}

Azure Retail Prices API tips (for `azure_retail_query`):
- Always include `priceType eq 'Consumption'` — excludes Reservations.
- Anchor on `armRegionName eq '<target_region>'`.
- For Flex Server DB: add `contains(productName, 'Flexible Server')`
  to exclude legacy Single-Server rows.
- For VMs: filter Linux meters (avoid `contains(meterName, 'Windows')`
  and `Spot` / `Low Priority`).
- When the meterName or productName looks legacy / unrelated to the
  modern SKU you want, refine your filter instead of just picking the
  first row back.
- When several rows match **spec** parity, **drop any row whose monthly
  equivalent would exceed the AWS monthly** you already computed, then among
  the rest **prefer the lower Azure `retailPrice`** — do not default to the
  first OData row.

Pricing norms (apply when translating tool results to `monthly_usd`):
- Hourly units → `monthly = hourly × 730`.
- GB/month units → `monthly_usd` is per-GB; write that in `assumptions`.
- If a service is purely usage-based, leave `monthly_usd` null AND set
  `note` to explain (e.g. "Standard LB is usage-based — first 5 rules free").

Spec snapshot rules:
- Fill `aws_spec` / `azure_spec` with the attributes returned by the Pricing
  API (vCPU, memory_gb, storage, engine, network).
- If fields aren't returned (rare), still include what you inferred.

Terraform-friendly SKU names for `azure_sku_suggestion`:
- VM:            `Standard_D2s_v5`, `Standard_B2s`
- PG / MySQL Flex: `B_Standard_B1ms`, `GP_Standard_D2ds_v5`, `MO_Standard_E2ds_v5`
- Managed Disk:   `Premium_LRS`, `StandardSSD_LRS`
- Storage Acct:   `Standard_LRS`, `Standard_GRS`
- Redis:          `Basic_C0`, `Standard_C1`

Output: return ONLY a JSON object matching the schema described in the user
message — no markdown, no commentary.  Set `monthly_delta_usd = azure_monthly - aws_monthly`
when BOTH sides have numbers; otherwise null.
"""


class AzureMappingAgent:
    """Per-resource mapping agent driven by function/tool calling."""

    def __init__(
        self,
        *,
        llm_deployment: str = "gpt-4o",
        azure_openai_endpoint: str | None = None,
        max_workers: int | None = None,
    ):
        self.llm_deployment = llm_deployment
        endpoint = (azure_openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT must be set.")
        self.logger = logger = logging.getLogger(__name__)

        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if api_key:
            self.client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                api_key=api_key,
                max_retries=int(os.getenv("AZURE_MAPPING_SDK_RETRIES", "1")),
                timeout=float(os.getenv("AZURE_MAPPING_TIMEOUT", "45")),
            )
            logger.info("AzureMappingAgent using API key auth")
        else:
            # Managed identity → DefaultAzureCredential chain.
            try:
                cred = ManagedIdentityCredential()
                token_provider = get_bearer_token_provider(
                    cred, "https://cognitiveservices.azure.com/.default"
                )
                # Probe — forces token fetch so we fail fast if MI isn't here.
                token_provider()
                logger.info("AzureMappingAgent using ManagedIdentity auth")
            except Exception:
                cred = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    cred, "https://cognitiveservices.azure.com/.default"
                )
                logger.info("AzureMappingAgent using DefaultAzureCredential auth")

            self.client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                azure_ad_token_provider=token_provider,
                max_retries=int(os.getenv("AZURE_MAPPING_SDK_RETRIES", "1")),
                timeout=float(os.getenv("AZURE_MAPPING_TIMEOUT", "45")),
            )

        self.max_workers = int(max_workers or os.getenv("AZURE_MAPPING_WORKERS", "6"))

    # ----- public entrypoint --------------------------------------------------
    def run(
        self,
        *,
        resources: List[Dict[str, Any]],
        target_azure_region: str = "eastus",
        source_aws_region: str = "",
    ) -> Dict[str, Any]:
        """Resolve mappings for all ``resources`` in parallel.

        Each resource is its own LLM conversation with tool-calling enabled,
        so one slow or failing resource doesn't stall the others.
        """
        if not resources:
            return {"mappings": [], "execution_log": ["No resources provided"]}

        execution_log: List[str] = [
            f"Azure mapping (tool-calling): {len(resources)} resource(s) → {target_azure_region}"
        ]

        # Preserve input order on output — threads complete out of order.
        outputs: List[Optional[Dict[str, Any]]] = [None] * len(resources)
        errors: List[Dict[str, Any]] = []
        n_workers = min(self.max_workers, max(1, len(resources)))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    self._map_one_resource,
                    resource=r,
                    target_azure_region=target_azure_region,
                    source_aws_region=str(r.get("region") or source_aws_region or ""),
                ): i
                for i, r in enumerate(resources)
            }
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    outputs[i] = fut.result()
                except Exception as e:
                    self.logger.exception("Mapping failed for row %d", i)
                    errors.append({"index": i, "error": str(e)})
                    # Placeholder so UI still renders the row.
                    outputs[i] = _placeholder_mapping(resources[i], str(e))

        execution_log.append(f"Completed {sum(1 for o in outputs if o)} mapping(s)")
        if errors:
            execution_log.append(f"{len(errors)} resource(s) failed; placeholders returned")

        return {
            "mappings": outputs,
            "execution_log": execution_log,
            "errors": errors,
        }

    # ----- one resource, one tool-calling conversation -----------------------
    def _map_one_resource(
        self,
        *,
        resource: Dict[str, Any],
        target_azure_region: str,
        source_aws_region: str,
    ) -> Dict[str, Any]:
        aws_key = (
            resource.get("aws_key")
            or resource.get("arn")
            or resource.get("id")
            or resource.get("name")
            or "unknown"
        )
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            aws_region_table=aws_region_table_markdown()
        )
        user_prompt = (
            "Map this ONE AWS resource to an Azure target. Use the tools to "
            "verify specs and fetch both sides' on-demand prices.\n\n"
            f"AWS resource (JSON):\n{json.dumps(resource, default=str)}\n\n"
            f"Source AWS region: {source_aws_region or '(not provided)'}\n"
            f"Target Azure region: {target_azure_region}\n\n"
            "When you have enough evidence, respond with ONLY the JSON object "
            "described by the `AzureTargetMapping` schema.  No markdown, no "
            "commentary, no code fence.\n\n"
            "Schema (abbreviated):\n"
            + _schema_summary_for_prompt()
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Tool-calling loop.
        max_iterations = int(os.getenv("AZURE_MAPPING_MAX_TOOL_ITERS", "8"))
        final_text = ""
        for iteration in range(max_iterations):
            response = self._chat_with_retry(messages)
            msg = response.choices[0].message
            # The SDK's ChatCompletionMessage -> dict conversion retains
            # tool_calls correctly; we need to forward it back for the model.
            messages.append(_assistant_msg_to_dict(msg))

            if not msg.tool_calls:
                final_text = msg.content or ""
                break

            for tc in msg.tool_calls:
                fn = tc.function
                try:
                    tool_output = execute_tool_call(fn.name, fn.arguments or "{}")
                except Exception as e:
                    tool_output = json.dumps({"ok": False, "error": str(e)})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    }
                )
        else:
            # Loop exhausted without a plain-text response — ask the model to
            # stop and emit the final answer using the accumulated evidence.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You've reached the tool-call budget. Return ONLY the final "
                        "JSON mapping now, using the evidence you already gathered."
                    ),
                }
            )
            response = self._chat_with_retry(messages, tool_choice="none")
            final_text = response.choices[0].message.content or ""

        return _parse_mapping_json(final_text, aws_key=aws_key, resource=resource)

    # ----- the single chat.completions.create with retry ---------------------
    def _chat_with_retry(
        self,
        messages: List[Dict[str, Any]],
        *,
        tool_choice: str | Any = "auto",
    ):
        max_attempts = int(os.getenv("AZURE_MAPPING_RETRIES", "3"))
        delay = 0.5
        last_err: Exception | None = None
        # Different model families want different token-limit parameter names
        # (gpt-4 → `max_tokens`; gpt-5 / o1 → `max_completion_tokens`).  Pick
        # the field based on the deployment name so callers don't have to care.
        token_kwargs: Dict[str, Any] = {}
        token_cap = int(os.getenv("AZURE_MAPPING_MAX_TOKENS", "2000"))
        depname_lower = (self.llm_deployment or "").lower()
        if any(tag in depname_lower for tag in ("gpt-5", "o1", "o3")):
            token_kwargs["max_completion_tokens"] = token_cap
        else:
            token_kwargs["max_tokens"] = token_cap
        for attempt in range(1, max_attempts + 1):
            try:
                return self.client.chat.completions.create(
                    model=self.llm_deployment,
                    messages=messages,
                    temperature=0.1,
                    tools=TOOLS if tool_choice != "none" else None,
                    tool_choice=tool_choice if tool_choice != "none" else None,
                    **token_kwargs,
                )
            except _RETRYABLE_EXC as e:
                last_err = e
                self.logger.warning(
                    "Azure mapping chat attempt %d/%d failed: %s",
                    attempt,
                    max_attempts,
                    e,
                )
                if attempt == max_attempts:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 4.0)
            except BadRequestError:
                raise
        assert last_err is not None
        raise last_err


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


def _assistant_msg_to_dict(msg: Any) -> Dict[str, Any]:
    """Convert ChatCompletionMessage back to the dict the API expects as input."""
    out: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return out


def _schema_summary_for_prompt() -> str:
    """A compact human-readable summary of ``AzureTargetMapping`` fields.

    Avoids dumping the full Pydantic JSON schema (hundreds of lines) while
    still telling the model exactly which keys to emit.
    """
    return (
        "{\n"
        '  "aws_key": str,\n'
        '  "aws_service": str,                # echo of input service\n'
        '  "aws_type": str,\n'
        '  "aws_name": str,\n'
        '  "aws_sku_hint": str,               # concrete class you priced, e.g. "t3.medium"\n'
        '  "aws_spec":    { "vcpu": str?, "memory_gb": str?, "storage": str?, "network": str?, "engine": str?, "extra": {} },\n'
        '  "aws_price":   { "monthly_usd": float?, "hourly_usd": float?, "unit_price_usd": float?, "unit": str?,\n'
        '                   "sku_resolved": str?, "meter": str?, "region": str?,\n'
        '                   "source": "aws-pricing-api", "source_url": str?, "as_of": str?,\n'
        '                   "assumptions": str?, "note": str? },\n'
        '  "azure_service": str,\n'
        '  "azure_resource_type": str,        # azurerm_* Terraform type\n'
        '  "azure_sku_suggestion": str,       # spec match to AWS; Azure monthly must be <= AWS monthly when both priced\n'
        '  "azure_spec":  { same shape as aws_spec },\n'
        '  "azure_price": { same shape as aws_price, source="azure-retail-prices" },\n'
        '  "monthly_delta_usd": float?,       # azure - aws; null if either is null\n'
        '  "rationale": str,                  # spec parity first; Azure price <= AWS when priced\n'
        '  "caveats": str\n'
        "}\n"
    )


def _parse_mapping_json(
    raw_text: str,
    *,
    aws_key: str,
    resource: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort JSON extraction + Pydantic validation.

    The LLM occasionally wraps JSON in a ```json fence despite the prompt
    ("Happens less with tool-calling-enabled models, but handle it anyway").
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        # Strip the leading "json" language tag if present.
        nl = text.find("\n")
        if nl != -1 and text[:nl].strip().lower() in ("json", "js"):
            text = text[nl + 1 :]
        text = text.strip("`").strip()

    try:
        obj = json.loads(text)
    except Exception as e:
        logger.warning("Mapping JSON parse failed for %s: %s", aws_key, e)
        return _placeholder_mapping(resource, f"LLM returned non-JSON: {e}")

    # Make sure the aws_key matches what we asked for (LLM sometimes drops it).
    if not obj.get("aws_key"):
        obj["aws_key"] = aws_key

    try:
        validated = AzureTargetMapping.model_validate(obj)
    except ValidationError as ve:
        logger.warning("Mapping schema validation failed for %s: %s", aws_key, ve)
        # Fall back to returning the raw dict so the UI still shows something.
        return {**obj, "_schema_error": str(ve)}

    return validated.model_dump()


def _placeholder_mapping(resource: Dict[str, Any], error: str) -> Dict[str, Any]:
    return {
        "aws_key": resource.get("aws_key")
        or resource.get("arn")
        or resource.get("id")
        or "unknown",
        "aws_service": str(resource.get("service") or ""),
        "aws_type": str(resource.get("type") or ""),
        "aws_name": str(resource.get("name") or ""),
        "aws_sku_hint": "",
        "aws_spec": {},
        "aws_price": {"note": "Not priced"},
        "azure_service": "",
        "azure_resource_type": "",
        "azure_sku_suggestion": "",
        "azure_spec": {},
        "azure_price": {"note": "Not priced"},
        "monthly_delta_usd": None,
        "rationale": "",
        "caveats": f"Mapping failed: {error}",
    }
