"""Strategy agent — single LLM call to produce migration waves, risks, open questions.

Does NOT generate Terraform — that's the deterministic generators' job.
This agent only produces narrative / planning content.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from openai import AzureOpenAI
from pydantic import BaseModel, Field

from .context import MigrationContext
from .schema import MigrationRisk, MigrationWave

logger = logging.getLogger(__name__)


class StrategyOutput(BaseModel):
    summary:        str = Field(description="2-3 sentence executive summary of the migration approach")
    assessment:     str = Field(description="Brief assessment of complexity, prerequisites, dependencies")
    waves:          list[MigrationWave] = Field(default_factory=list)
    risks:          list[MigrationRisk] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
당신은 시니어 클라우드 마이그레이션 아키텍트입니다.  주어진 AWS 아키텍처
스냅샷과 Azure 매핑 결과(이미 결정됨)를 보고 **마이그레이션 전략 문서**만
작성하세요.

**작성하지 않는 것:**
  - Terraform HCL (별도 결정론적 생성기가 만듦)
  - 구체적 SKU/타입 선정 (이미 매핑 단계에서 끝남)

**작성할 것:**
  1. summary — 2~3문장으로 마이그레이션 접근 요약 (한국어)
  2. assessment — 복잡도, 사전 조건, 주요 의존성 (한국어, 5문장 이내)
  3. waves — 실행 순서가 있는 단계 배열 (3~6개):
       Wave 1: Networking (VNet, Subnet, NSG)
       Wave 2: Storage (Blob)
       Wave 3: Database (Azure DB) — 데이터 이전 창 필요
       Wave 4: Compute (VM)
       Wave 5: Cutover (DNS 전환)
     각 wave는 name, description, resources(이름 목록), blockers(선행 조건).
  4. risks — 식별된 리스크 (3~6개): category, detail, mitigation 모두 한국어.
  5. open_questions — 사용자가 결정해야 할 미해결 질문 (2~5개), 한국어.

모든 자연어는 **한국어**로.  리소스 이름/타입/SKU는 영문 원문 그대로.
"""


def _build_client(llm_deployment: str, endpoint: str) -> AzureOpenAI:
    """Create an Azure OpenAI client matching how the rest of the project does it."""
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if api_key:
        return AzureOpenAI(
            azure_endpoint=endpoint.rstrip("/"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            api_key=api_key,
            max_retries=int(os.getenv("AZURE_MAPPING_SDK_RETRIES", "1")),
            timeout=float(os.getenv("AZURE_MAPPING_TIMEOUT", "60")),
        )

    env_type = (os.getenv("ENVIRONMENT") or "dev").lower()
    if env_type == "local":
        cred = DefaultAzureCredential()
    else:
        mid = os.getenv("MANAGED_IDENTITY_CLIENT_ID")
        cred = ManagedIdentityCredential(client_id=mid) if mid else DefaultAzureCredential()
    token_provider = get_bearer_token_provider(cred, "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(
        azure_endpoint=endpoint.rstrip("/"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        azure_ad_token_provider=token_provider,
        max_retries=int(os.getenv("AZURE_OPENAI_MAX_RETRIES", "3")),
        timeout=float(os.getenv("AZURE_OPENAI_TIMEOUT", "120")),
    )


def _build_user_prompt(ctx: MigrationContext) -> str:
    """Compact, structured input — not raw text dumping."""
    stats = ctx.stats()

    # A small sample of resource names for grounding
    sample = {
        "vpcs":   [{"id": v.get("id"), "cidr": v.get("cidr"), "subnet_count": len(v.get("subnets") or [])} for v in ctx.get_vpcs()[:5]],
        "ec2":    [{"id": e.get("id"), "name": e.get("name"), "type": e.get("instance_type"), "subnet": e.get("subnet_id")} for e in ctx.get_ec2()[:10]],
        "rds":    [{"id": d.get("id"), "engine": d.get("engine"), "class": d.get("instance_class")} for d in ctx.get_rds()[:5]],
        "s3":     [{"name": b.get("name"), "region": b.get("region")} for b in ctx.get_s3()[:10]],
        "lambda": [{"name": l.get("name"), "runtime": l.get("runtime")} for l in ctx.get_lambda()[:5]],
    }

    mapping_summary = [
        {
            "aws":   m.get("aws_name") or m.get("aws_key"),
            "type":  m.get("aws_type"),
            "azure": m.get("azure_service"),
            "tf":    m.get("azure_resource_type"),
        }
        for m in ctx.mappings[:30]
    ]

    pc = ctx.policy_constraints or {}
    pc_block = ""
    if pc and not pc.get("error"):
        pc_block = (
            "\n대상 sub 의 Azure Policy 제약 (terraform 코드는 이미 반영됨):\n"
            f"{json.dumps({k: pc.get(k) for k in ('required_tags','tag_defaults','allowed_locations','manual_review')}, ensure_ascii=False, default=str)}\n"
            "→ 이 제약을 risks/open_questions 에 반영해 주세요 "
            "(예: 'TBD 로 채워진 필수 태그를 실제 값으로 입력해야 한다')."
        )

    return (
        f"AWS 계정: {ctx.get_account_id()} / 리전: {ctx.get_source_region()}\n"
        f"Azure 대상 리전: {ctx.target_region}\n"
        f"마이그레이션 목표: {ctx.goals or '(미입력)'}\n\n"
        f"리소스 통계: {json.dumps(stats, ensure_ascii=False)}\n\n"
        f"리소스 샘플 (최대):\n{json.dumps(sample, ensure_ascii=False, default=str)}\n\n"
        f"이미 결정된 Azure 매핑 (참고용):\n{json.dumps(mapping_summary, ensure_ascii=False, default=str)}\n"
        f"{pc_block}\n"
        "위 정보로 마이그레이션 전략 문서(StrategyOutput)를 작성하세요."
    )


def generate_strategy(ctx: MigrationContext, llm_deployment: str, endpoint: str) -> StrategyOutput:
    """Single LLM call → StrategyOutput (waves, risks, summary)."""
    client = _build_client(llm_deployment, endpoint)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": _build_user_prompt(ctx)},
    ]

    try:
        completion = client.beta.chat.completions.parse(
            model=llm_deployment,
            messages=messages,
            response_format=StrategyOutput,
        )
        msg = completion.choices[0].message
        if getattr(msg, "refusal", None):
            raise RuntimeError(msg.refusal)
        if msg.parsed is None:
            raise RuntimeError("Strategy agent returned no parsed output")
        return msg.parsed
    except Exception as e:
        logger.exception("Strategy generation failed: %s", e)
        # Return a minimal fallback so the pipeline can still produce Terraform
        stats = ctx.stats()
        return StrategyOutput(
            summary=f"AWS 계정 {ctx.get_account_id()} 의 {stats['ec2']}개 EC2, {stats['rds']}개 RDS, {stats['s3']}개 S3를 Azure {ctx.target_region}으로 마이그레이션합니다.",
            assessment=f"Strategy LLM 호출 실패 — 결정론적 Terraform 생성은 정상 진행. 오류: {e}",
            waves=[
                MigrationWave(order=1, name="Networking",   description="VNet, Subnet, NSG 생성"),
                MigrationWave(order=2, name="Storage",      description="Storage Account 생성 + 데이터 이전"),
                MigrationWave(order=3, name="Database",     description="Azure DB 생성 + 데이터 이전 (유지보수 창)"),
                MigrationWave(order=4, name="Compute",      description="VM 프로비저닝 + 애플리케이션 이전"),
                MigrationWave(order=5, name="Cutover",      description="DNS 전환 및 검증"),
            ],
            risks=[
                MigrationRisk(category="Operations", detail="Strategy LLM 호출이 실패해 자동 평가가 누락됨", mitigation="배포 전 수동 검토 권장"),
            ],
            open_questions=["Azure Hybrid Benefit 사용 여부", "유지보수 창(시간) 결정"],
        )
