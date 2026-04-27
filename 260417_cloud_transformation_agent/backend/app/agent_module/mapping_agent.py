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
당신은 시니어 클라우드 마이그레이션 아키텍트이자 가격 분석가입니다.

**응답 언어 (필수):** 최종 JSON에서 사람이 읽는 설명 —
`rationale`, `caveats`, `aws_price.assumptions`, `aws_price.note`,
`azure_price.assumptions`, `azure_price.note` —
는 **반드시 자연스러운 한국어**로 작성합니다.
리소스 타입, SKU, Terraform `azurerm_*` 타입, 툴 함수명, API 필터 문자열, 숫자,
통화(USD) 표기는 **영문·원문 그대로** 둡니다.

**작업 (AWS 리소스 1개당):**
  1. 구체적인 AWS SKU / 인스턴스 클래스 / 스토리지 클래스를 식별합니다.
     입력에 이미 클래스가 있으면(`t3.medium`, `db.t3.medium`, `gp3` 등) 그대로 쓰고,
     없으면 리소스 유형·태그·이름에서 추론합니다.
  2. `aws_pricing_query`로 AWS 사양(vCPU, RAM 등)을 확인하고,
     해당 리소스 **소스 Region**의 온디맨드 시간당 가격을 조회합니다.
  3. 적절한 Azure 서비스 패밀리를 정합니다(아래 매핑 표가 강한 기본값이며,
     리소스 스펙/태그가 명백히 다르면 예외).
  4. `azure_retail_query`로 **대상 Azure Region**의 후보 SKU를 조회한 뒤,
     **스펙 정합성(vCPU·RAM·스토리지 등급·엔진·범용 vs 버스트·가용성 계층)**을
     기준으로 **단 하나**의 최적 SKU를 고릅니다.
     **AWS와의 가격 유사도는 선정 기준이 아닙니다** — **유사 용량/스펙**이 우선입니다.
  4b. **가격 제약 (양쪽에 월액이 모두 있을 때 필수):**
     기록하는 Azure 온디맨드 **월액**은 동일 비교 기준의 AWS 온디맨드 **월액**을
     **넘지 않아야** 합니다 (`Azure 월액 ≤ AWS 월액`, `monthly_usd`가 양쪽 모두 있을 때).
     - 먼저 AWS 워크로드 스펙에 잘 맞는 Azure SKU만 1차로 좁힙니다.
     - 그 목록에서 **AWS 월액보다 비싼 월액**인 SKU는 제외하고 남은 것에서 고릅니다.
       스펙에 충분히 맞으면서도 ≤ AWS 인 SKU가 **없으면**, ≤ AWS를 만족하는
       SKU가 있다면 그중 **스펙이 가장 가까운 것**을 고릅니다.
       정말 불가능하면 `caveats`에 **한국어로** 명확히 적고, 더 비싼 Azure SKU를
       **조용히 선택하지 마세요**.
     - 스펙이 맞고 **Azure ≤ AWS**를 만족하는 옵션들 사이에서는 Azure 월액이
       더 낮은 쪽을 선호할 수 있습니다(스펙이 여전히 유효한 전제).
     - `rationale`에는 **먼저 스펙이 AWS와 어떻게 맞는지**를 쓰고,
       가격은 보조적으로만(예: "이 티어에서 Azure 월액이 AWS 이하") 언급합니다.
  5. 선택한 SKU에 대해 `azure_retail_query`로 정확한 온디맨드 월 가격을 다시 확인합니다.
     시간 단위 미터면 `730 h/mo`로 환산합니다. Lambda, Cosmos serverless, Standard LB,
     Functions, Log Analytics, Key Vault 등 순수 종량제는 `monthly_usd`는 null로 두고
     `note`에 **한국어로** 이유를 적습니다.
  6. `AzureTargetMapping` 스키마에 맞는 **JSON 객체 하나만** 반환합니다.
     산문, 코드 펜스, 마크다운 없음. 모든 달러 금액은 **툴 응답에서만** 가져오고
     임의로 만들지 **마세요**.

표준 AWS → Azure 매핑 (강한 기본값):

- EC2 Instance                → `azurerm_linux_virtual_machine` / `_windows_virtual_machine`
- EC2 LaunchTemplate / ASG    → `azurerm_linux_virtual_machine_scale_set`
- EC2 EBS Volume              → `azurerm_managed_disk`
- EC2 Security Group          → `azurerm_network_security_group` (대개 무료)
- EC2 VPC / Subnet / Route    → `azurerm_virtual_network` / `_subnet` / `_route_table` (무료)
- EC2 NAT Gateway             → `azurerm_nat_gateway`
- EC2 EIP                     → `azurerm_public_ip`
- RDS (Postgres)              → `azurerm_postgresql_flexible_server`
- RDS (MySQL/MariaDB)         → `azurerm_mysql_flexible_server`
- RDS (SQL Server)            → `azurerm_mssql_database` / `_mssql_managed_instance`
- RDS (Aurora)                → `azurerm_postgresql_flexible_server` / `_mysql_flexible_server` (엔진 주의)
- S3 Bucket                   → `azurerm_storage_account`
- DynamoDB Table              → `azurerm_cosmosdb_account` (SQL API)
- ElastiCache Redis           → `azurerm_redis_cache`
- Lambda Function             → `azurerm_linux_function_app` (종량제)
- ECS/Fargate                 → `azurerm_container_app`  (대규모 K8s → `_kubernetes_cluster`)
- EKS                         → `azurerm_kubernetes_cluster`
- Application LB              → `azurerm_application_gateway`
- Network LB / Classic        → `azurerm_lb`
- CloudFront                  → `azurerm_cdn_frontdoor_profile`
- Route 53                    → `azurerm_dns_zone`
- Secrets Manager / SSM PS    → `azurerm_key_vault`
- KMS                         → `azurerm_key_vault_key`
- IAM Role / Policy           → `azurerm_role_assignment` (무료)
- SNS                         → `azurerm_eventgrid_topic` or Service Bus
- SQS                         → `azurerm_servicebus_queue`
- Kinesis / MSK               → `azurerm_eventhub_namespace`
- CloudWatch Logs             → `azurerm_log_analytics_workspace`
- EFS                         → `azurerm_storage_share`

AWS region 코드 → AWS Pricing API `location` 값 (필터에 사용):

{aws_region_table}

`azure_retail_query` 팁 (Azure Retail Prices API):
- 항상 `priceType eq 'Consumption'` 포함 — Reservation 제외.
- `armRegionName eq '<target_region>'` 고정.
- Flexible Server DB: `contains(productName, 'Flexible Server')`로 레거시 Single-Server 행 제외.
- VM: Linux 미터 위주 (`contains(meterName, 'Windows')`, Spot/Low Priority 제외).
- meterName/productName이 원하는 현대 SKU와 맞지 않으면 첫 행만 고르지 말고 필터를 정제합니다.
- **스펙**이 비슷한 여러 행이면, 이미 알고 있는 **AWS 월액**을 초과하는 월 환산 행은 버리고,
  남은 것 중 `retailPrice`가 낮은 쪽을 선호합니다 — OData 첫 행에만 의존하지 마세요.

가격 규칙 (`monthly_usd`로 옮길 때):
- 시간 단위 → `월액 = 시간당 × 730`.
- GB/월 단위 → `monthly_usd`가 per-GB이면 `assumptions`에 **한국어로** 적습니다.
- 순수 종량제면 `monthly_usd`는 null, `note`에 **한국어로** 설명합니다.

스펙 스냅샷:
- `aws_spec` / `azure_spec`에는 Pricing API가 돌려준 속성을 채웁니다 (vCPU, memory_gb, storage, engine, network).
- 반환되지 않은 필드는 드물며, 추론한 내용은 그대로 포함합니다.

Terraform 친화적 `azure_sku_suggestion` 예:
- VM:            `Standard_D2s_v5`, `Standard_B2s`
- PG / MySQL Flex: `B_Standard_B1ms`, `GP_Standard_D2ds_v5`, `MO_Standard_E2ds_v5`
- Managed Disk:   `Premium_LRS`, `StandardSSD_LRS`
- Storage Acct:   `Standard_LRS`, `Standard_GRS`
- Redis:          `Basic_C0`, `Standard_C1`

출력: 사용자 메시지의 스키마와 일치하는 **JSON 한 개만** 반환합니다.
`monthly_delta_usd = azure_monthly - aws_monthly` — 양쪽 모두 숫자일 때만, 아니면 null.
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
            return {"mappings": [], "execution_log": ["리소스가 제공되지 않았습니다"]}

        execution_log: List[str] = [
            f"Azure 매핑(툴 호출): 리소스 {len(resources)}개 → {target_azure_region}"
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

        execution_log.append(f"완료: 매핑 {sum(1 for o in outputs if o)}건")
        if errors:
            execution_log.append(f"실패 {len(errors)}건 — 자리 표시 결과 반환")

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
            "아래 **하나**의 AWS 리소스를 Azure 대상으로 매핑하세요. 툴로 사양을 검증하고 "
            "양쪽 온디맨드 가격을 조회합니다.\n\n"
            f"AWS resource (JSON):\n{json.dumps(resource, default=str)}\n\n"
            f"소스 AWS Region: {source_aws_region or '(미입력)'}\n"
            f"대상 Azure Region: {target_azure_region}\n\n"
            "증거가 충분하면 `AzureTargetMapping` 스키마에 맞는 **JSON 한 개만** 반환하세요. "
            "마크다운·코드 펜스·부가 설명 없음.\n\n"
            "스키마 요약:\n"
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
                        "툴 호출 한도에 도달했습니다. 지금까지 모은 근거만으로 "
                        "최종 매핑 JSON만 반환하세요. 다른 텍스트 없음."
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
        '  "aws_service": str,\n'
        '  "aws_type": str,\n'
        '  "aws_name": str,\n'
        '  "aws_sku_hint": str,\n'
        '  "aws_spec":    { "vcpu": str?, "memory_gb": str?, "storage": str?, "network": str?, "engine": str?, "extra": {} },\n'
        '  "aws_price":   { "monthly_usd": float?, "hourly_usd": float?, "unit_price_usd": float?, "unit": str?,\n'
        '                   "sku_resolved": str?, "meter": str?, "region": str?,\n'
        '                   "source": "aws-pricing-api", "source_url": str?, "as_of": str?,\n'
        '                   "assumptions": str?, "note": str? },  // 설명은 한국어\n'
        '  "azure_service": str,\n'
        '  "azure_resource_type": str,\n'
        '  "azure_sku_suggestion": str,\n'
        '  "azure_spec":  { aws_spec와 동일 형태 },\n'
        '  "azure_price": { aws_price와 동일 형태, source="azure-retail-prices" },\n'
        '  "monthly_delta_usd": float?,  // azure - aws; 하나라도 null이면 null\n'
        '  "rationale": str,             // 선정 근거 — 한국어, 스펙 우선\n'
        '  "caveats": str                // 주의사항 — 한국어\n'
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
        return _placeholder_mapping(resource, f"LLM이 JSON이 아닌 응답을 반환: {e}")

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
        "aws_price": {"note": "가격 미산출"},
        "azure_service": "",
        "azure_resource_type": "",
        "azure_sku_suggestion": "",
        "azure_spec": {},
        "azure_price": {"note": "가격 미산출"},
        "monthly_delta_usd": None,
        "rationale": "",
        "caveats": f"매핑 실패: {error}",
    }
