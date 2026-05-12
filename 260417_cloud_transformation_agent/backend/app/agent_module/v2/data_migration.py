"""LLM-driven data migration script generation.

Replaces the rule-based ``generate_data_migration_scripts`` for AWS→Azure
data movement.  The LLM examines each mapped resource and emits per-resource
shell command sequences via the ``emit_migration_script`` tool.

Returns a list of ``DataMigrationScript`` ready to be embedded in the plan.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .context import MigrationContext
from .schema import DataMigrationScript
from .strategy import _build_client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Tool definition (one emit per AWS source that needs data migration)
# ──────────────────────────────────────────────────────────────────

_TOOL_EMIT_SCRIPT = {
    "type": "function",
    "function": {
        "name": "emit_migration_script",
        "description": (
            "Emit one data migration script for a single AWS source resource. "
            "Call this once per AWS resource that requires data movement to "
            "its Azure target (S3 bucket, RDS instance, DynamoDB table, "
            "ElastiCache, etc.).  Resources without runtime data (security "
            "groups, IAM roles, Lambda code, compute config) should NOT be "
            "emitted — they are re-created from terraform, not migrated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "AWS resource identifier — the bucket name, RDS instance id, table name, etc.",
                },
                "type": {
                    "type": "string",
                    "description": "Short type label — s3 | rds | dynamodb | elasticache | ebs | dms | other.",
                },
                "title": {
                    "type": "string",
                    "description": 'Human-readable Korean title, e.g. "S3 → Blob Storage 데이터 복사 (bucket-foo)".',
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered shell commands.  Each step is a single command (or a tightly-related pipe).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title":   {"type": "string", "description": "Step title in Korean."},
                            "command": {"type": "string", "description": "Exact shell command, copy-pasteable."},
                            "notes":   {"type": "string", "description": "Korean notes — placeholders, prerequisites, gotchas.  Empty string OK."},
                        },
                        "required": ["title", "command", "notes"],
                    },
                },
                "notes": {
                    "type": "string",
                    "description": "Korean summary for the whole script (prereqs, recommended downtime window, etc.).  Empty string OK.",
                },
            },
            "required": ["resource", "type", "title", "steps", "notes"],
        },
    },
}

_TOOLS = [_TOOL_EMIT_SCRIPT]


# ──────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
당신은 AWS → Azure 데이터 이전 시나리오를 설계하는 시니어 클라우드 엔지니어
입니다.  입력으로 받은 매핑된 리소스 목록을 보고, 각 AWS 원본 리소스에서
Azure 대상 리소스로 데이터를 옮기는 **즉시 실행 가능한 shell 스크립트**를
``emit_migration_script`` 도구로 한 번씩 호출해서 만들어 주세요.

## 어떤 리소스가 대상인가

**데이터 이전이 필요한 (emit 해야 함):**
- S3 버킷 → Azure Blob Storage (azurerm_storage_account + container)
- RDS / Aurora → Azure DB (PostgreSQL / MySQL / SQL Database)
- DynamoDB → Azure Cosmos DB
- ElastiCache (Redis/Memcached) → Azure Cache for Redis
- EBS Snapshot → Azure Managed Disk (드물지만 emit 가능)
- Glacier / S3 Standard-IA → Azure Archive Storage

**데이터 이전이 필요 없는 (emit 하지 마세요):**
- VPC / Subnet / Security Group — terraform 으로 재생성
- EC2 / Lambda / ALB / NLB / Auto Scaling Group — terraform 으로 재생성
- IAM Role / Policy — Azure RBAC 으로 별도 매핑
- Route 53 / CloudFront — 별도 DNS cutover 단계

## 스크립트 작성 원칙

1. **도구 / CLI 선택:**
   • S3 → Blob: ``aws s3 sync s3://<bucket> .`` + ``azcopy copy``
     (또는 ``rclone`` 으로 직접 사이트 간 복사)
   • RDS PostgreSQL → Azure DB for PostgreSQL:
     ``pg_dump`` → ``pg_restore`` 또는 Azure Database Migration Service (DMS).
   • RDS MySQL → Azure DB for MySQL:
     ``mysqldump`` → ``mysql`` import 또는 DMS.
   • DynamoDB → Cosmos DB:
     ``aws dynamodb scan ... > out.json`` 후 Cosmos DB Data Migration Tool
     (``dt.exe``) 또는 Azure Data Factory.
   • ElastiCache Redis → Azure Cache for Redis:
     ``redis-cli --rdb`` 로 RDB 덤프 → Azure Redis ``redis-cli ... migrate``.

2. **각 단계는 단일 명령**: 한 step 의 command 는 한 줄 또는 잘 묶인 파이프.
   복잡한 분기는 별도 step 으로 분리.

3. **자격증명 / 변수**: 실제 비밀번호, connection string 등은 ``${...}`` 환경
   변수 placeholder 로.  사용자가 채워야 한다는 점은 step 의 notes 에 명시.
   예: ``export AZ_STORAGE_KEY=...``, ``export PGPASSWORD=...``.

4. **prereqs 는 별도 step 또는 notes 에**: AWS CLI / Azure CLI / azcopy /
   pg_dump 등이 PATH 에 있어야 한다면 첫 step 에 install 명령 또는 notes 로
   안내.

5. **resource 필드는 AWS 원본 식별자만**: 예시 — S3 버킷 이름,
   RDS instance identifier, DynamoDB table name.  Azure 대상 정보는 command
   안에 들어감.

6. **모든 자연어 (title, notes) 는 한국어**.  command 는 그대로 영문.

7. 데이터 이전이 필요 없는 plan (compute / network 만 있을 때) 이면 도구를
   한 번도 호출하지 말고 짧은 한국어 메시지로 마무리.

## 도구 사용 패턴

- 매 AWS 원본 리소스마다 ``emit_migration_script`` 한 번 호출.
- 모든 emit 끝나면 도구 호출 없이 한국어 한 줄 요약 메시지를 반환 → 종료.

작성된 스크립트는 사용자가 deploy 단계의 데이터 이전 패널에서 그대로
복사/실행할 수 있어야 합니다.
"""


# ──────────────────────────────────────────────────────────────────
# Input trimming
# ──────────────────────────────────────────────────────────────────

def _data_relevant_mappings(mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only mappings whose AWS source carries runtime data."""
    keep_types = {"s3", "rds", "dynamodb", "elasticache", "redshift"}
    out = []
    for m in mappings or []:
        if not m:
            continue
        atype = (m.get("aws_type") or "").lower()
        if any(t in atype for t in keep_types):
            out.append({
                "aws_key":             m.get("aws_key") or m.get("arn"),
                "aws_name":            m.get("aws_name"),
                "aws_type":            m.get("aws_type"),
                "azure_service":       m.get("azure_service"),
                "azure_resource_type": m.get("azure_resource_type"),
                "azure_sku":           m.get("azure_sku_suggestion") or m.get("azure_sku"),
                "azure_region":        m.get("azure_region"),
                "notes":               m.get("notes"),
            })
    return out


def _data_relevant_arch(arch: Dict[str, Any]) -> Dict[str, Any]:
    """Project the AWS architecture down to data-carrying resources."""
    out: Dict[str, Any] = {
        "account_id":   arch.get("account_id"),
        "region":       arch.get("region"),
    }
    for key in ("rds", "s3"):
        items = arch.get(key) or []
        out[key] = [{k: v for k, v in r.items() if k != "raw"} for r in items[:50]]
    return out


# ──────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────

def generate_data_migration_scripts(
    ctx: MigrationContext,
    *,
    llm_deployment: str,
    azure_openai_endpoint: str,
    max_iters: int = 20,
) -> Tuple[List[DataMigrationScript], List[str]]:
    """Run the tool-calling LLM agent.

    Returns ``(scripts, log_lines)``.  Raises on hard LLM failure.  Empty
    list is a valid response (no data-carrying resources).
    """
    log: List[str] = []

    mappings_in = _data_relevant_mappings(ctx.mappings or [])
    if not mappings_in:
        log.append("데이터 이전 대상 리소스 없음 (S3/RDS/DynamoDB/ElastiCache 등 0건) — LLM 호출 생략")
        return [], log

    payload = {
        "aws_architecture": _data_relevant_arch(ctx.architecture or {}),
        "azure_mappings":   mappings_in,
        "azure_region":     ctx.target_region,
        "migration_goals":  ctx.goals or "",
    }
    user_prompt = (
        "다음 입력으로 AWS → Azure 데이터 이전 shell 스크립트를 작성하세요.  "
        "``emit_migration_script`` 도구를 매 AWS 원본 리소스마다 한 번씩 호출.  "
        "모든 emit 끝나면 도구 호출 없이 한국어 한 줄 요약으로 마무리.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)}\n```"
    )

    client = _build_client(llm_deployment, azure_openai_endpoint)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]

    scripts: List[DataMigrationScript] = []
    final_message = ""

    for it in range(max_iters):
        try:
            completion = client.chat.completions.create(
                model=llm_deployment,
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            log.append(f"LLM 호출 실패 (iter={it}): {e}")
            raise

        msg = completion.choices[0].message
        assistant_turn: Dict[str, Any] = {
            "role":    "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id":       tc.id,
                    "type":     "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if not msg.tool_calls:
            final_message = msg.content or ""
            log.append(f"iter={it}: LLM 종료 — {final_message[:120]}")
            break

        for tc in msg.tool_calls:
            if tc.function.name != "emit_migration_script":
                log.append(f"iter={it}: ⚠ 알 수 없는 도구 호출 {tc.function.name!r}")
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"unknown tool: {tc.function.name}",
                })
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                # Coerce steps so each item has {title, command, notes}
                raw_steps = args.get("steps") or []
                steps = []
                for s in raw_steps:
                    if not isinstance(s, dict):
                        continue
                    steps.append({
                        "title":   str(s.get("title")   or ""),
                        "command": str(s.get("command") or ""),
                        "notes":   str(s.get("notes")   or ""),
                    })
                script = DataMigrationScript(
                    resource=str(args.get("resource") or ""),
                    type=str(args.get("type") or "other"),
                    title=str(args.get("title") or ""),
                    steps=steps,
                    notes=str(args.get("notes") or ""),
                )
                scripts.append(script)
                tool_result = f"ok: emitted {script.type} script for {script.resource} ({len(script.steps)} steps)"
                log.append(
                    f"iter={it}: emit_migration_script({script.resource!r}, {script.type}) — "
                    f"{len(script.steps)} steps"
                )
            except Exception as e:
                tool_result = f"error: {e}"
                log.append(f"iter={it}: ⚠ emit 실패: {e}")
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      tool_result,
            })
    else:
        log.append(f"⚠ max_iters={max_iters} 도달 — {len(scripts)}개 스크립트로 진행")

    log.append(f"데이터 이전 스크립트 LLM 완료 → {len(scripts)}개 — {final_message[:120]}")
    return scripts, log
