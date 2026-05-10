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
from typing import Any, Dict, List, Optional, Tuple

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

**🔒 절대 규칙 — 도구 우선순위 (모든 Azure 리소스 type 에 동일 적용):**

  azure_query 의 region 가용 SKU 목록 = **유일한 ground truth**.
  azure_retail_query 는 **가격 비교 전용** — *가용성 근거가 아닙니다*.

  ❌ 잘못된 추론:
    "Retail 가격 행이 있으니 Standard_B1s 도 사용 가능"
    → Retail Prices 는 글로벌 가격표라서 region 에 실제 배포 가능한지와 무관합니다.
    → terraform apply 시 'SKU not available' / 'NotAvailableForSubscription' 으로 막힘.

  ✓ 올바른 추론:
    1) azure_query 로 region 의 가용 SKU 목록을 받는다 (`restrictions` 비어있는 것만)
    2) AWS 스펙과 호환되는 후보들을 그 목록 *안에서만* 추린다
    3) 후보들의 가격을 azure_retail_query 로 비교한다
    4) 그 중에서 최적 SKU 를 고른다 — 가격행이 없으면 그 SKU 는 후보에서 제외

  이 규칙은 VM·Disk·Storage Account·Postgres·Redis·Network·KeyVault 등
  **모든 Azure 리소스 type 에 동일하게 적용**됩니다.

**작업 (AWS 리소스 1개당) — 순서가 중요:**
  1. AWS SKU / 인스턴스 클래스 / 스토리지 클래스를 식별 (입력에 있으면 그대로,
     없으면 리소스 유형·태그·이름에서 추론).
  2. `aws_pricing_query`로 AWS 사양(vCPU, RAM 등)을 확인하고, 소스 Region 의
     온디맨드 시간당 가격을 조회.
  3. Azure 서비스 패밀리를 정함 (아래 매핑 표가 강한 기본값).
  4. **🔒 region 가용성 fence — 절대 건너뛰지 말 것:**
     `azure_query` 로 대상 region 의 *가용* SKU 목록을 조회.
       VM 예: ['vm','list-skus','--location','<region>','--resource-type','virtualMachines',
              '--size','<family-prefix>',
              '--query','[?length(restrictions || `[]`)==`0`].name']
     이 호출이 반환한 **이름 목록만이 후보 풀**입니다. 여기에 없는 SKU 는
     **절대 추천하지 마세요** — Retail 에 가격이 있어도 X.
     **응답이 `data_truncated: true` 면 `--query` 더 좁혀 재호출**하세요.
     절대 trimmed 결과만으로 "가용" 판단 X.
  5. `azure_policies_for_type` 로 이 type 의 정책 (deny / 필수 태그 / 허용 region)
     을 가져와 4번 후보 풀을 더 좁힘 (정책 deny 위반 SKU 제외).
  6. 4~5번에서 살아남은 *후보 풀 안에서만* AWS 스펙과 정합성 가장 좋은
     SKU 를 1순위로 고르고, 그 SKU 에 대해 `azure_retail_query` 로 정확한
     가격을 받아 비교합니다.
     **AWS 와의 가격 유사도는 선정 기준이 아닙니다** — **유사 용량/스펙**이 우선.

  ⚠ 만약 후보 풀에 스펙 호환 SKU 가 0 개면, **거짓 매핑을 만들지 말고**
  `caveats` 에 한국어로 "region 에 호환 SKU 없음, 다른 region/SKU 필요" 명시.
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
     - `rationale` 에 "Retail 가격 행이 확인되었다" 식으로 **가격행 존재를 가용성
       근거로 쓰지 마세요** — 가용성 근거는 *반드시* `azure_query` 로 받은
       region 가용 SKU 이름 목록입니다.  올바른 표현 예:
         ✓ "azure_query 로 koreacentral 가용 SKU 중 Standard_B2as_v2 가
            B-시리즈 v2 의 가장 작은 옵션이라 t3.micro 와 매칭"
         ❌ "Retail 가격 검증으로 Standard_B1s 사용 가능 확인"
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

**region 가용성 / 정책 사전 검증 — 매핑 결정 전 반드시 확인:**

- `azure_query` (read-only az CLI):
  대상 region 에서 후보 SKU 가 실제로 가용한지 확인합니다.
  **VM 만 있는 게 아닙니다** — 모든 Azure 리소스 type 에 사용 가능.

  ⚠ **반드시 `--query` 로 결과를 좁히세요.** 좁히지 않으면 응답이 trim 되어
     원하는 SKU 가 누락될 수 있습니다 (`data_truncated: true` 가 신호).

    VM 가용 SKU만:
      ['vm','list-skus','--location','<region>','--resource-type','virtualMachines',
       '--size','Standard_B',          # 패밀리 prefix 필터
       '--query','[?length(restrictions || `[]`)==`0`].name']
    특정 SKU 가용성 직접 확인:
      ['vm','list-skus','--location','<region>',
       '--query',"[?name=='Standard_B2as_v2'].{{name:name,restrictions:restrictions}}"]
    Disk:      ['vm','list-skus','--location','<region>','--resource-type','disks',
                '--query','[?length(restrictions || `[]`)==`0`].name']
    Storage:   ['storage','account','list-skus','--location','<region>',
                '--query','[].{{name:name,tier:tier,kind:kind}}']
    Postgres:  ['postgres','flexible-server','list-skus','--location','<region>']
    Network usage: ['network','list-usages','--location','<region>',
                    '--query','[?currentValue >= `limit`]']

  결과의 `restrictions` 가 비어있는 SKU 만 추천.  region 에 없거나 restricted 면
  같은 패밀리의 다른 SKU 로 대체.  **응답에 `data_truncated: true` 가 있으면**
  → `--query` 더 좁혀서 재호출 (절대 trimmed 결과만으로 "not available" 결론짓지 말 것).

- `azure_policies_for_type`:
  대상 sub 에서 이 Azure type 에 영향을 주는 정책만 골라옵니다 (예:
  `Microsoft.Compute/virtualMachines` 면 VM 관련 deny + universal tag/location 정책).
  매핑 시 **반드시 이 정책의 제약을 위반하지 않도록** SKU/region 을 고르세요:
  - `effect: "deny"` 정책의 조건을 어기는 SKU 는 후보에서 제외
  - universal 정책 (tags 요구, allowed locations) 은 caveats / 매핑 메모에 반영

`azure_retail_query` 팁 (Azure Retail Prices API):
- 항상 `priceType eq 'Consumption'` 포함 — Reservation 제외.
- `armRegionName eq '<target_region>'` 고정.
- Flexible Server DB: `contains(productName, 'Flexible Server')`로 레거시 Single-Server 행 제외.
- VM: Linux 미터 위주 (`contains(meterName, 'Windows')`, Spot/Low Priority 제외).
- meterName/productName이 원하는 현대 SKU와 맞지 않으면 첫 행만 고르지 말고 필터를 정제합니다.
- **스펙**이 비슷한 여러 행이면, 이미 알고 있는 **AWS 월액**을 초과하는 월 환산 행은 버리고,
  남은 것 중 `retailPrice`가 낮은 쪽을 선호합니다 — OData 첫 행에만 의존하지 마세요.

**필터 복잡도 한도 (중요):**
- Azure Retail Prices 는 conjunct 가 많으면 HTTP 400 으로 거부합니다.
- 권장: **eq 절 4개 이하 + contains/not contains 절 1~2개** 까지만.
- `armSkuName eq` 가 이미 있으면 `contains(productName, ...)` 는 보통 redundant — 빼세요.
- `not contains(meterName, 'Windows')` + `not contains(meterName, 'Spot')` 식으로 **부정 절 2개를 동시에** 넣으면 자주 400 이 납니다.
  → 하나만 남기고, 나머지는 결과 items 를 받은 후 reasoning 에서 메뉴얼 필터.
- 400 이 나도 시스템이 자동으로 필터를 단순화해 retry 합니다 (응답에 `simplified_from` 필드가 보일 수 있음).
  그 경우 받은 items 가 더 많을 수 있으니 직접 Windows/Spot 행 등은 걸러서 사용하세요.

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

**`cost_insight` (필수, 양쪽 monthly_usd 가 모두 있을 때):**
이 필드는 사용자에게 **비용 절감 메시지**를 직접 전달합니다. 반드시 채우세요.

  monthly_savings_usd  = round(aws_monthly - azure_monthly, 2)        # +이면 Azure 저렴
  annual_savings_usd   = round(monthly_savings_usd * 12, 2)
  savings_pct          = round(monthly_savings_usd / aws_monthly * 100, 1)

  category 결정 (savings_pct 기반):
    >= +5  → "savings"      (Azure가 더 저렴)
    -5..+5 → "neutral"      (사실상 동등)
    <  -5  → "premium"      (Azure가 더 비쌈 — 가능하면 피하되, 스펙·SLA·기능 우위가 있으면 명시)

  양쪽 중 한쪽이라도 종량제(monthly_usd = null)면:
    savings_pct / monthly_savings_usd / annual_savings_usd = null
    category = "usage-based"

  양쪽 모두 0(VPC/Subnet/SG/IAM 등 무료 구성)이면:
    category = "free", 모든 숫자 = 0

  **`headline` (한국어, 1줄, 사용자가 한 번에 이해할 수 있게):**
    savings:     "월 32% 절감 · 연 $540 절감"           (절감액과 비율 모두)
    neutral:     "AWS와 비슷한 가격대"
    premium:     "월 $15 더 비쌈 (12% 추가)"            (그리고 caveats에 이유 보강)
    usage-based: "종량제 — 실 사용량에 비례"
    free:        "무료 구성 요소"

**`cost_tips` (선택, 적용 가능한 경우 0~3개를 한국어 한 줄로):**
다음 조건에 부합하면 cost_tips 배열에 추가하세요. 부합하지 않으면 빈 배열로 둡니다.

- VM이 비핵심·개발·테스트 워크로드일 가능성(이름이나 태그에 'dev'/'test'/'staging'/'qa' 포함):
   "Burstable B-series 사용 시 월 50%+ 절감 가능 (비핵심 워크로드)"
- VM이 Windows 라이선스를 사용할 가능성:
   "기존 Windows Server 라이선스 보유 시 Azure Hybrid Benefit으로 추가 40% 절감"
- DB가 트래픽 변동 큰 워크로드:
   "Burstable 티어(B1ms, B2s) 사용 시 월 70%+ 절감 가능 (변동 트래픽)"
- Storage가 콜드 데이터일 가능성(아카이브, 로그, 백업 추정):
   "Cool 또는 Archive tier 사용 시 월 50~80% 절감 가능"
- 모든 priced VM/DB(가장 일반적):
   "1년 Reserved Instance 적용 시 약 40% 절감 / 3년 약정 시 약 60% 절감"
- 컨테이너/배치 워크로드:
   "Spot VM 사용 시 월 60~90% 절감 가능 (중단 가능 워크로드)"

각 팁은 독립적이고 행동 가능한 한 줄이어야 합니다. 본 매핑(spec parity)을 변경하지 마세요 —
팁은 사용자가 검토할 추가 절감 옵션입니다.

**`monthly_1yr_ri_usd` / `monthly_3yr_ri_usd`:**
가능하면 채우지 말고 비워두세요(null) — 시스템이 자동으로 Reserved Instance 가격을 조회해 채웁니다.
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
        target_subscription_id: str = "",
    ) -> Dict[str, Any]:
        """Resolve mappings for all ``resources``.

        Pipeline:
          1. Static mapping for no-SKU resources (VPC/Subnet/SG/IAM/...).  No LLM.
          2. Dedup remaining resources by canonical SKU key — only one LLM
             call per unique (type+SKU+engine) combination, then broadcast.
          3. Representative resources are batched into groups of
             ``AZURE_MAPPING_BATCH_SIZE`` and sent to the LLM together.
        """
        if not resources:
            return {"mappings": [], "execution_log": ["리소스가 제공되지 않았습니다"]}

        n = len(resources)
        outputs: List[Optional[Dict[str, Any]]] = [None] * n
        errors: List[Dict[str, Any]] = []
        execution_log: List[str] = [
            f"Azure 매핑: 리소스 {n}개 → {target_azure_region}"
        ]

        # ── Pass 1: static mappings (no LLM) ───────────────────────
        needs_llm: List[int] = []
        static_count = 0
        for i, r in enumerate(resources):
            sm = _static_mapping(r)
            if sm is not None:
                outputs[i] = sm
                static_count += 1
            else:
                needs_llm.append(i)
        if static_count:
            execution_log.append(f"정적 매핑: {static_count}건 (LLM 호출 없음)")

        # ── Pass 2: dedup by canonical SKU key ─────────────────────
        groups: Dict[str, List[int]] = {}
        for i in needs_llm:
            key = _dedup_key(resources[i])
            groups.setdefault(key, []).append(i)

        if not groups:
            execution_log.append("완료: 정적 매핑만 사용")
            return {"mappings": outputs, "execution_log": execution_log, "errors": errors}

        rep_indices = [grp[0] for grp in groups.values()]
        if len(rep_indices) < len(needs_llm):
            execution_log.append(
                f"중복 제거: {len(needs_llm)} → {len(rep_indices)}개 고유 SKU "
                f"(LLM 호출 {len(rep_indices)}회로 단축)"
            )

        # ── Pass 3: batch the unique representatives ───────────────
        batch_size = max(1, int(os.getenv("AZURE_MAPPING_BATCH_SIZE", "5")))
        batches: List[List[int]] = [
            rep_indices[i : i + batch_size] for i in range(0, len(rep_indices), batch_size)
        ]
        execution_log.append(
            f"배치: {len(batches)}개 (배치 크기 ≤{batch_size}, 병렬 ≤{self.max_workers})"
        )

        # Run batches in parallel
        rep_results: Dict[int, Dict[str, Any]] = {}

        def _run_batch(batch_idx_list: List[int]) -> List[Dict[str, Any]]:
            batch_resources = [resources[i] for i in batch_idx_list]
            if len(batch_resources) == 1:
                # Single-resource path — keeps the existing simpler prompt
                src = str(batch_resources[0].get("region") or source_aws_region or "")
                return [self._map_one_resource(
                    resource=batch_resources[0],
                    target_azure_region=target_azure_region,
                    source_aws_region=src,
                    target_subscription_id=target_subscription_id,
                )]
            return self._map_batch(
                batch=batch_resources,
                target_azure_region=target_azure_region,
                source_aws_region=source_aws_region,
                target_subscription_id=target_subscription_id,
            )

        n_workers = min(self.max_workers, max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_run_batch, b): b for b in batches}
            for fut in as_completed(futures):
                batch_idx_list = futures[fut]
                try:
                    batch_mappings = fut.result()
                    for rep_i, mapping in zip(batch_idx_list, batch_mappings):
                        rep_results[rep_i] = mapping
                except Exception as e:
                    self.logger.exception("Batch mapping failed")
                    for rep_i in batch_idx_list:
                        errors.append({"index": rep_i, "error": str(e)})
                        rep_results[rep_i] = _placeholder_mapping(resources[rep_i], str(e))

        # ── Pass 4: broadcast representative results to group members ─
        for key, idx_list in groups.items():
            rep_i = idx_list[0]
            rep_mapping = rep_results.get(rep_i)
            if rep_mapping is None:
                continue
            for i in idx_list:
                r = resources[i]
                outputs[i] = {
                    **rep_mapping,
                    "aws_key":  r.get("arn") or r.get("id") or r.get("name") or "unknown",
                    "aws_name": r.get("name") or r.get("id") or "",
                }

        # ── Pass 5: enrich with Reserved Instance (1y/3y) pricing ──
        try:
            _enrich_with_ri_pricing(outputs, target_azure_region, self.max_workers)
            ri_priced = sum(
                1 for m in outputs
                if m and (m.get("azure_price") or {}).get("monthly_3yr_ri_usd") is not None
            )
            if ri_priced:
                execution_log.append(f"Reserved Instance 가격 조회: {ri_priced}건 적용")
        except Exception as e:
            self.logger.warning("RI pricing enrichment failed: %s", e)

        # ── Pass 6: ensure cost_insight is filled for every mapping ──
        for m in outputs:
            if m is not None:
                _ensure_cost_insight(m)

        # ── Pass 7: workload-wide TCO summary (on-demand + RI) ─────
        summary = _compute_tco_summary(outputs)

        # Cache stats (helps debugging perf)
        try:
            from .pricing_tools import cache_stats
            cs = cache_stats()
            execution_log.append(
                f"캐시: 적중 {cs['hits']}, 미스 {cs['misses']}, 항목 {cs['size']}"
            )
        except Exception:
            pass

        execution_log.append(f"완료: 매핑 {sum(1 for o in outputs if o)}건")
        if errors:
            execution_log.append(f"실패 {len(errors)}건 — 자리 표시 결과 반환")
        if summary["compared_count"] > 0:
            execution_log.append(
                f"TCO: AWS ${summary['total_aws_monthly_usd']:.2f}/월 → "
                f"Azure ${summary['total_azure_monthly_usd']:.2f}/월 "
                f"(연 ${summary['annual_savings_usd']:.0f} 절감, {summary['savings_pct']:.1f}%)"
            )

        return {
            "mappings": outputs,
            "summary": summary,
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
        target_subscription_id: str = "",
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
        sub_line = (
            f"대상 Azure Subscription ID: {target_subscription_id}\n"
            "  (azure_query / azure_policies_for_type 호출 시 이 값을 사용하세요)\n"
            if target_subscription_id else ""
        )
        user_prompt = (
            "아래 **하나**의 AWS 리소스를 Azure 대상으로 매핑하세요. 툴로 사양을 검증하고 "
            "양쪽 온디맨드 가격을 조회합니다.\n\n"
            f"AWS resource (JSON):\n{json.dumps(resource, default=str)}\n\n"
            f"소스 AWS Region: {source_aws_region or '(미입력)'}\n"
            f"대상 Azure Region: {target_azure_region}\n"
            f"{sub_line}\n"
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

    # ----- batch path: multiple resources in one tool-calling conversation ---
    def _map_batch(
        self,
        *,
        batch: List[Dict[str, Any]],
        target_azure_region: str,
        source_aws_region: str,
        target_subscription_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Map several unique resources in a single LLM conversation.

        The LLM keeps tool-call context across resources (e.g. enumerating
        Azure VM SKUs once and reusing for several EC2s in the batch),
        and returns a JSON array — one mapping per input, in order.
        """
        n = len(batch)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            aws_region_table=aws_region_table_markdown()
        )
        sub_line = (
            f"대상 Azure Subscription ID: {target_subscription_id}\n"
            "  (azure_query / azure_policies_for_type 호출 시 이 값을 사용하세요)\n"
            if target_subscription_id else ""
        )
        user_prompt = (
            f"아래 **{n}개의** AWS 리소스를 각각 Azure 대상으로 매핑하세요. "
            f"필요한 만큼 `aws_pricing_query`/`azure_retail_query`/`azure_query`/"
            f"`azure_policies_for_type` 툴을 호출해 각 리소스의 사양/가격/region "
            f"가용성/정책 제약을 검증한 뒤, 입력 순서를 유지하여 "
            f"`AzureTargetMapping` 객체의 **JSON 배열**로 반환합니다.\n\n"
            f"AWS resources (JSON array):\n{json.dumps(batch, default=str)}\n\n"
            f"소스 AWS Region 기본값: {source_aws_region or '(미입력)'}\n"
            f"대상 Azure Region: {target_azure_region}\n"
            f"{sub_line}\n"
            "출력 형식 (마크다운/코드펜스 없음, 순수 JSON 배열):\n"
            "[\n"
            "  { ... AzureTargetMapping object 1 ... },\n"
            "  { ... AzureTargetMapping object 2 ... },\n"
            "  ...\n"
            "]\n\n"
            "각 객체의 스키마 요약:\n"
            + _schema_summary_for_prompt()
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # More iterations + larger token cap for batch
        max_iterations = int(os.getenv("AZURE_MAPPING_MAX_TOOL_ITERS", "8")) * max(1, min(n, 4))
        final_text = ""
        for iteration in range(max_iterations):
            response = self._chat_with_retry(messages, batch_size=n)
            msg = response.choices[0].message
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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_output,
                })
        else:
            messages.append({
                "role": "user",
                "content": (
                    "툴 호출 한도에 도달했습니다. 지금까지 모은 근거만으로 "
                    f"{n}개 리소스의 최종 매핑 JSON 배열만 반환하세요. 다른 텍스트 없음."
                ),
            })
            response = self._chat_with_retry(messages, tool_choice="none", batch_size=n)
            final_text = response.choices[0].message.content or ""

        return _parse_mapping_array(final_text, batch=batch)

    # ----- the single chat.completions.create with retry ---------------------
    def _chat_with_retry(
        self,
        messages: List[Dict[str, Any]],
        *,
        tool_choice: str | Any = "auto",
        batch_size: int = 1,
    ):
        max_attempts = int(os.getenv("AZURE_MAPPING_RETRIES", "3"))
        delay = 0.5
        last_err: Exception | None = None
        # Different model families want different token-limit parameter names
        # (gpt-4 → `max_tokens`; gpt-5 / o1 → `max_completion_tokens`).  Pick
        # the field based on the deployment name so callers don't have to care.
        token_kwargs: Dict[str, Any] = {}
        # Scale token cap with batch size — each AzureTargetMapping is ~600 tokens
        per_resource_cap = int(os.getenv("AZURE_MAPPING_MAX_TOKENS", "2000"))
        token_cap = per_resource_cap * max(1, batch_size)
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


# ── Reserved Instance (1y/3y) pricing lookup ──────────────────────
def _fetch_ri_pricing(arm_sku: str, region: str) -> Dict[str, Optional[float]]:
    """Look up 1-year and 3-year Reserved Instance monthly pricing for a SKU.

    Returns ``{monthly_1yr_ri_usd, monthly_3yr_ri_usd}`` (either may be None).
    Goes through ``execute_tool_call`` so the result is cached alongside
    on-demand pricing queries.
    """
    if not arm_sku:
        return {"monthly_1yr_ri_usd": None, "monthly_3yr_ri_usd": None}

    filter_expr = (
        f"armSkuName eq '{arm_sku}' and "
        f"armRegionName eq '{region}' and "
        f"priceType eq 'Reservation'"
    )
    try:
        raw = execute_tool_call("azure_retail_query", json.dumps({
            "filter_expr": filter_expr,
            "top": 20,
            "max_items": 20,
        }))
        data = json.loads(raw)
    except Exception:
        return {"monthly_1yr_ri_usd": None, "monthly_3yr_ri_usd": None}

    one_yr: Optional[float] = None
    three_yr: Optional[float] = None
    for row in (data.get("items") or []):
        term = (row.get("reservationTerm") or "").lower()
        price = row.get("retailPrice")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        # `retailPrice` is the *total* upfront cost for the reservation period.
        if "1 year" in term and one_yr is None:
            one_yr = round(float(price) / 12.0, 2)
        elif "3 year" in term and three_yr is None:
            three_yr = round(float(price) / 36.0, 2)
        if one_yr is not None and three_yr is not None:
            break

    return {"monthly_1yr_ri_usd": one_yr, "monthly_3yr_ri_usd": three_yr}


def _enrich_with_ri_pricing(
    mappings: List[Optional[Dict[str, Any]]],
    region: str,
    max_workers: int = 6,
) -> None:
    """Populate ``azure_price.monthly_{1yr,3yr}_ri_usd`` for each mapping in-place.

    Looked up in parallel; deduplicated by SKU within the batch so we never
    query the same SKU twice (the caller's pricing cache also helps across
    batches).
    """
    # Collect unique (sku, region) pairs that need RI lookup
    unique_skus: Dict[str, List[Dict[str, Any]]] = {}
    for m in mappings:
        if not m:
            continue
        azp = m.get("azure_price") or {}
        # Skip if already has RI prices
        if azp.get("monthly_1yr_ri_usd") is not None or azp.get("monthly_3yr_ri_usd") is not None:
            continue
        sku = azp.get("sku_resolved") or ""
        # Skip usage-based / no monthly
        if not isinstance(azp.get("monthly_usd"), (int, float)) or not sku:
            continue
        unique_skus.setdefault(sku, []).append(m)

    if not unique_skus:
        return

    def _lookup(sku: str) -> Tuple[str, Dict[str, Optional[float]]]:
        return sku, _fetch_ri_pricing(sku, region)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_skus))) as pool:
        futures = {pool.submit(_lookup, sku): sku for sku in unique_skus}
        for fut in as_completed(futures):
            try:
                sku, ri = fut.result()
            except Exception:
                continue
            for m in unique_skus[sku]:
                m["azure_price"]["monthly_1yr_ri_usd"] = ri["monthly_1yr_ri_usd"]
                m["azure_price"]["monthly_3yr_ri_usd"] = ri["monthly_3yr_ri_usd"]


# ── Cost insight back-fill ─────────────────────────────────────────
def _ensure_cost_insight(mapping: Dict[str, Any]) -> None:
    """Make sure ``mapping['cost_insight']`` is filled, even if the LLM omitted it.

    Recomputes everything from the priced AWS / Azure monthlies so the UI
    can rely on this field always being populated.
    """
    aws_p   = (mapping.get("aws_price")   or {}).get("monthly_usd")
    azure_p = (mapping.get("azure_price") or {}).get("monthly_usd")

    ci = mapping.get("cost_insight")
    if not isinstance(ci, dict):
        ci = {}

    # Both priced
    if isinstance(aws_p, (int, float)) and isinstance(azure_p, (int, float)):
        if aws_p == 0 and azure_p == 0:
            ci.setdefault("category", "free")
            ci.setdefault("savings_pct", 0.0)
            ci.setdefault("monthly_savings_usd", 0.0)
            ci.setdefault("annual_savings_usd", 0.0)
            ci.setdefault("headline", "무료 구성 요소")
        else:
            monthly_save = round(aws_p - azure_p, 2)
            annual_save  = round(monthly_save * 12, 2)
            pct = round((monthly_save / aws_p) * 100, 1) if aws_p > 0 else 0.0
            if pct >= 5.0:
                cat = "savings"
                head = f"월 {pct:.1f}% 절감 · 연 ${annual_save:,.0f} 절감"
            elif pct <= -5.0:
                cat = "premium"
                head = f"월 ${abs(monthly_save):.2f} 더 비쌈 ({abs(pct):.1f}% 추가)"
            else:
                cat = "neutral"
                head = "AWS와 비슷한 가격대"
            ci["savings_pct"]         = pct
            ci["monthly_savings_usd"] = monthly_save
            ci["annual_savings_usd"]  = annual_save
            ci["category"]            = cat
            if not ci.get("headline"):
                ci["headline"] = head
    else:
        # Usage-based or one side missing
        ci.setdefault("savings_pct", None)
        ci.setdefault("monthly_savings_usd", None)
        ci.setdefault("annual_savings_usd", None)
        ci.setdefault("category", "usage-based")
        if not ci.get("headline"):
            ci["headline"] = "종량제 — 실 사용량에 비례"

    mapping["cost_insight"] = ci


# ── Workload TCO summary ──────────────────────────────────────────
def _compute_tco_summary(mappings: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate per-resource costs into a workload-wide TCO summary.

    Computes three scenarios:
      • on-demand:      AWS PAYG vs Azure PAYG
      • azure-1yr-ri:   AWS PAYG vs Azure 1-year reservation
      • azure-3yr-ri:   AWS PAYG vs Azure 3-year reservation

    For RI scenarios, resources without RI pricing fall back to on-demand.
    """
    total_aws        = 0.0
    total_azure      = 0.0
    total_azure_1yr  = 0.0
    total_azure_3yr  = 0.0
    has_any_ri_1yr   = False
    has_any_ri_3yr   = False
    compared = 0
    usage_based = 0
    free_count = 0
    total = 0
    savings_resources: List[str] = []
    premium_resources: List[str] = []
    cost_tips_aggregated: List[str] = []

    for m in mappings:
        if not m:
            continue
        total += 1
        aws_p   = (m.get("aws_price")   or {}).get("monthly_usd")
        azure_p_obj = m.get("azure_price") or {}
        azure_p = azure_p_obj.get("monthly_usd")
        azure_1yr = azure_p_obj.get("monthly_1yr_ri_usd")
        azure_3yr = azure_p_obj.get("monthly_3yr_ri_usd")

        if isinstance(aws_p, (int, float)) and isinstance(azure_p, (int, float)):
            total_aws   += float(aws_p)
            total_azure += float(azure_p)
            # RI fallback to on-demand if RI not available for this SKU
            if isinstance(azure_1yr, (int, float)):
                total_azure_1yr += float(azure_1yr)
                has_any_ri_1yr = True
            else:
                total_azure_1yr += float(azure_p)
            if isinstance(azure_3yr, (int, float)):
                total_azure_3yr += float(azure_3yr)
                has_any_ri_3yr = True
            else:
                total_azure_3yr += float(azure_p)

            if aws_p == 0 and azure_p == 0:
                free_count += 1
            else:
                compared += 1
                cat = (m.get("cost_insight") or {}).get("category")
                name = m.get("aws_name") or m.get("aws_key") or ""
                if cat == "savings":
                    savings_resources.append(name)
                elif cat == "premium":
                    premium_resources.append(name)
        else:
            usage_based += 1

        # Aggregate unique cost tips
        for tip in (m.get("cost_tips") or []):
            if tip and tip not in cost_tips_aggregated:
                cost_tips_aggregated.append(tip)

    monthly_save = round(total_aws - total_azure, 2)
    annual_save  = round(monthly_save * 12, 2)
    pct = round((monthly_save / total_aws) * 100, 1) if total_aws > 0 else 0.0

    monthly_save_1yr = round(total_aws - total_azure_1yr, 2)
    pct_1yr = round((monthly_save_1yr / total_aws) * 100, 1) if total_aws > 0 else 0.0

    monthly_save_3yr = round(total_aws - total_azure_3yr, 2)
    pct_3yr = round((monthly_save_3yr / total_aws) * 100, 1) if total_aws > 0 else 0.0

    return {
        # ── On-demand scenario ─────────────────────────
        "total_aws_monthly_usd":     round(total_aws, 2),
        "total_azure_monthly_usd":   round(total_azure, 2),
        "monthly_savings_usd":       monthly_save,
        "annual_savings_usd":        annual_save,
        "three_year_savings_usd":    round(monthly_save * 36, 2),
        "savings_pct":               pct,
        # ── 1-year Reserved Instance scenario ─────────
        "total_azure_1yr_ri_usd":    round(total_azure_1yr, 2),
        "monthly_savings_1yr_usd":   monthly_save_1yr,
        "annual_savings_1yr_usd":    round(monthly_save_1yr * 12, 2),
        "savings_pct_1yr":           pct_1yr,
        "has_ri_1yr":                has_any_ri_1yr,
        # ── 3-year Reserved Instance scenario ─────────
        "total_azure_3yr_ri_usd":    round(total_azure_3yr, 2),
        "monthly_savings_3yr_usd":   monthly_save_3yr,
        "three_year_savings_3yr_usd":round(monthly_save_3yr * 36, 2),
        "savings_pct_3yr":           pct_3yr,
        "has_ri_3yr":                has_any_ri_3yr,
        # ── Counts & resource lists ───────────────────
        "compared_count":            compared,
        "usage_based_count":         usage_based,
        "free_count":                free_count,
        "total_count":               total,
        "savings_resource_names":    savings_resources[:10],
        "premium_resource_names":    premium_resources[:10],
        "aggregated_cost_tips":      cost_tips_aggregated[:8],
    }


# ── Static mappings ─────────────────────────────────────────────────
# No-SKU resources (network primitives, IAM): pricing is zero-or-flat-rate
# and the Azure target is invariant — skip the LLM entirely.
_STATIC_MAPPINGS: Dict[str, Dict[str, str]] = {
    "ec2/vpc":              {"svc": "Virtual Network",          "tf": "azurerm_virtual_network"},
    "ec2/subnet":           {"svc": "Subnet",                   "tf": "azurerm_subnet"},
    "ec2/security-group":   {"svc": "Network Security Group",   "tf": "azurerm_network_security_group"},
    "ec2/route-table":      {"svc": "Route Table",              "tf": "azurerm_route_table"},
    "ec2/internet-gateway": {"svc": "Virtual Network (built-in)","tf": "azurerm_virtual_network"},
    "ec2/nat-gateway":      {"svc": "NAT Gateway",              "tf": "azurerm_nat_gateway"},
    "ec2/network-acl":      {"svc": "NSG (rules)",              "tf": "azurerm_network_security_group"},
    "ec2/elastic-ip":       {"svc": "Public IP",                "tf": "azurerm_public_ip"},
    "iam/role":             {"svc": "Azure RBAC Role Assignment","tf": "azurerm_role_assignment"},
    "iam/policy":           {"svc": "Azure Custom Role",        "tf": "azurerm_role_definition"},
    "iam/instance-profile": {"svc": "Managed Identity",         "tf": "azurerm_user_assigned_identity"},
}


def _static_mapping(resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a static mapping dict for no-SKU resources, or None."""
    t = (resource.get("_type") or "").lower()
    spec = _STATIC_MAPPINGS.get(t)
    if not spec:
        return None
    return {
        "aws_key":              resource.get("arn") or resource.get("id") or "unknown",
        "aws_service":          str(resource.get("service") or t.split("/")[0].upper()),
        "aws_type":             t.split("/")[1] if "/" in t else "",
        "aws_name":             str(resource.get("name") or resource.get("id") or ""),
        "aws_sku_hint":         "",
        "aws_spec":             {},
        "aws_price":            {"monthly_usd": 0.0, "note": "네트워크/IAM 구성 요소 — 별도 비용 없음"},
        "azure_service":        spec["svc"],
        "azure_resource_type":  spec["tf"],
        "azure_sku_suggestion": "",
        "azure_spec":            {},
        "azure_price":          {"monthly_usd": 0.0, "note": "구성 요소 — 별도 비용 없음"},
        "monthly_delta_usd":    0.0,
        "cost_insight": {
            "savings_pct":          0.0,
            "monthly_savings_usd":  0.0,
            "annual_savings_usd":   0.0,
            "headline":             "무료 구성 요소",
            "category":             "free",
        },
        "rationale":            f"{t} → {spec['svc']}: 표준 네트워크/IAM 매핑 (가격 없음)",
        "caveats":              "",
        "cost_tips":            [],
    }


def _dedup_key(r: Dict[str, Any]) -> str:
    """Canonical key — resources sharing this key get the same Azure mapping.

    Includes only spec dimensions that affect the chosen SKU and price.
    Different ARNs but identical specs → one LLM call for the group.
    """
    t = (r.get("_type") or "").lower()
    if t == "ec2":
        # Same instance_type + OS → same Azure VM SKU
        details = r.get("details") or {}
        return f"ec2:{details.get('instance_type') or r.get('instance_type') or '?'}"
    if t == "rds":
        details = r.get("details") or {}
        return (f"rds:{details.get('engine') or r.get('engine') or '?'}"
                f":{details.get('instance_class') or r.get('instance_class') or '?'}"
                f":{details.get('multi_az')}")
    if t == "lambda":
        details = r.get("details") or {}
        return f"lambda:{details.get('runtime') or r.get('runtime') or '?'}:{details.get('memory_mb') or r.get('memory_mb') or '?'}"
    if t == "s3":
        # All S3 buckets → same Azure Storage mapping
        return "s3:standard"
    if t in ("elb", "elasticloadbalancing"):
        details = r.get("details") or {}
        return f"elb:{details.get('type') or r.get('type') or '?'}:{details.get('scheme') or r.get('scheme') or '?'}"
    if t == "elasticache":
        details = r.get("details") or {}
        return f"elasticache:{details.get('engine') or '?'}:{details.get('cache_node_type') or '?'}"
    if t == "ecs":
        return "ecs:cluster"
    if t == "dynamodb":
        return "dynamodb:default"
    # Default: each resource is its own group (safest)
    return r.get("arn") or f"{t}:{r.get('id') or r.get('name') or 'unknown'}"


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
        '  "cost_insight": {            // ★ 비용 절감 메시지 (필수)\n'
        '     "savings_pct":           float?,  // +이면 Azure 저렴, %\n'
        '     "monthly_savings_usd":   float?,  // +이면 Azure 저렴\n'
        '     "annual_savings_usd":    float?,  // monthly × 12\n'
        '     "headline":              str,     // 한국어 한 줄 (예: "월 32% 절감 · 연 $540 절감")\n'
        '     "category":              "savings" | "neutral" | "premium" | "usage-based" | "free"\n'
        '  },\n'
        '  "rationale": str,             // 선정 근거 — 한국어, 스펙 우선\n'
        '  "caveats": str,               // 주의사항 — 한국어\n'
        '  "cost_tips": [str, ...]       // ★ 비용 최적화 팁 — 한국어 한 줄, 0~3개\n'
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


def _parse_mapping_array(
    raw_text: str,
    *,
    batch: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Parse the LLM's batch response into ``len(batch)`` mappings.

    Accepts:
      - A bare JSON array: ``[ {...}, {...} ]``
      - A wrapped object:  ``{ "mappings": [ ... ] }``
    Falls back to placeholder entries for any missing/invalid items so the
    caller always gets exactly ``len(batch)`` results in the same order.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1 and text[:nl].strip().lower() in ("json", "js"):
            text = text[nl + 1 :]
        text = text.strip("`").strip()

    try:
        obj = json.loads(text)
    except Exception as e:
        logger.warning("Batch mapping JSON parse failed: %s", e)
        return [_placeholder_mapping(r, f"LLM이 JSON 배열이 아닌 응답을 반환: {e}") for r in batch]

    arr = obj.get("mappings") if isinstance(obj, dict) else obj
    if not isinstance(arr, list):
        return [_placeholder_mapping(r, "응답이 배열이 아님") for r in batch]

    out: List[Dict[str, Any]] = []
    for i, r in enumerate(batch):
        try:
            item = arr[i]
        except IndexError:
            out.append(_placeholder_mapping(r, "응답 배열 길이 부족"))
            continue
        if not item.get("aws_key"):
            item["aws_key"] = r.get("arn") or r.get("id") or r.get("name") or "unknown"
        try:
            validated = AzureTargetMapping.model_validate(item)
            out.append(validated.model_dump())
        except ValidationError as ve:
            logger.warning("Batch item %d schema invalid: %s", i, ve)
            out.append({**item, "_schema_error": str(ve)})
    return out


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
