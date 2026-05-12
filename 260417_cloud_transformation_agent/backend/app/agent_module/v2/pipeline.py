"""V2 pipeline orchestrator.

Wires together: Strategy → Generators → Wiring → Validation → Data Migration.
Returns a single ``MigrationPlanV2`` dict ready to serialize.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from .code_generator import generate_terraform_code
from .context import MigrationContext
from .schema import DataMigrationScript, MigrationPlanV2, TerraformModule
from .strategy import generate_strategy
from .validator import validate_terraform, write_modules_to_disk

logger = logging.getLogger(__name__)


def _generate_data_migrations(ctx: MigrationContext) -> List[DataMigrationScript]:
    """Reuse the existing rule-based data migration script generator."""
    from app.routers.plan import generate_data_migration_scripts

    # Build the resources payload that endpoint expects
    resources = []
    for db in ctx.get_rds():
        resources.append({
            "_type":    "rds",
            "id":       db.get("id"),
            "name":     db.get("id"),
            "arn":      db.get("arn"),
            "engine":   db.get("engine"),
            "endpoint": db.get("endpoint"),
        })
    for s3 in ctx.get_s3():
        resources.append({
            "_type": "s3",
            "id":    s3.get("name"),
            "name":  s3.get("name"),
            "arn":   s3.get("arn"),
        })

    if not resources:
        return []

    body = {"resources": resources, "azure_region": ctx.target_region}
    try:
        result = generate_data_migration_scripts(body)
        return [DataMigrationScript(**s) for s in (result.get("scripts") or [])]
    except Exception as e:
        logger.warning("Data migration generation failed: %s", e)
        return []


def run_migration_v2(
    ctx: MigrationContext,
    *,
    llm_deployment: str,
    azure_openai_endpoint: str,
    skip_validation: bool = False,
) -> Dict[str, Any]:
    """Run the v2 migration pipeline end-to-end.

    Args:
        ctx: Discovery graph + Mappings.
        llm_deployment: Azure OpenAI deployment name (only used for strategy step).
        azure_openai_endpoint: Azure OpenAI endpoint URL.
        skip_validation: If True, skip the ``terraform validate`` step
            (useful for unit tests or environments without terraform).

    Returns:
        ``MigrationPlanV2`` as a dict (serialization-ready).
    """
    pipeline_log: List[str] = []
    started = time.time()

    # ── Step 0: Azure Policy constraints (deterministic, optional) ──
    # If we know the target subscription, pull policy-derived constraints
    # (required tags, allowed locations, etc.) so the root generator can
    # bake them into the terraform code.
    if ctx.target_subscription_id and ctx.policy_constraints is None:
        pipeline_log.append(f"Step 0/5: Azure Policy 제약 추출 (sub={ctx.target_subscription_id})")
        t0 = time.time()
        try:
            from app.services.azure_policy import extract_constraints
            ctx.policy_constraints = extract_constraints(ctx.target_subscription_id)
            c = ctx.policy_constraints
            fo = c.get('field_operations') or []
            diag = c.get('diagnostics') or {}
            pipeline_log.append(
                f"  • {time.time() - t0:.1f}s — assignments={diag.get('raw_assignment_count', '?')}, "
                f"exemptions={diag.get('exemptions_count', 0)}, "
                f"rules={diag.get('rule_count', 0)} (exempt {diag.get('exempt_rule_count', 0)}), "
                f"DENY={diag.get('deny_count', 0)} MODIFY={diag.get('modify_count', 0)}"
            )
            pipeline_log.append(
                f"    · path: {diag.get('fetch_path') or '?'}, "
                f"required_tags={c.get('required_tags') or []}, "
                f"allowed_locations={c.get('allowed_locations') or []}"
            )
            mt = diag.get('modify_target_types') or []
            if mt:
                pipeline_log.append(f"    · MODIFY target types: {mt}")
            for op in fo[:10]:
                ops_list = op.get('operations') or []
                first = ""
                if ops_list and isinstance(ops_list[0], dict):
                    first = f"  [{ops_list[0].get('field','?')} → {ops_list[0].get('value','?')!r}]"
                pipeline_log.append(
                    f"    · [MODIFY] {op.get('policy_name') or '(no name)'} "
                    f"→ {op.get('azure_type') or '(any)'}: {len(ops_list)} ops{first}"
                )
            if len(fo) > 10:
                pipeline_log.append(f"    · MODIFY …외 {len(fo) - 10}건")
            mr = c.get('manual_review') or []
            for d in mr[:5]:
                pipeline_log.append(
                    f"    · [DENY]  {d.get('name') or '(no name)'} "
                    f"→ {d.get('resourceType') or '(unknown)'}"
                )
            if len(mr) > 5:
                pipeline_log.append(f"    · DENY …외 {len(mr) - 5}건")
        except Exception as e:
            ctx.policy_constraints = {"error": str(e)}
            pipeline_log.append(f"  • Policy 조회 실패 (정책 미반영): {e}")
    elif not ctx.target_subscription_id:
        pipeline_log.append("Step 0/5: Azure Policy 제약 추출 — 건너뜀 (target_subscription_id 미설정)")

    # ── Step 1: Strategy (LLM) ────────────────────────────────────
    pipeline_log.append("Step 1/5: Strategy (LLM 1회)")
    t0 = time.time()
    strategy = generate_strategy(ctx, llm_deployment, azure_openai_endpoint)
    pipeline_log.append(f"  • {time.time() - t0:.1f}s — waves={len(strategy.waves)}, risks={len(strategy.risks)}")

    # ── Step 2: Terraform 코드 생성 (LLM) ─────────────────────────
    # 매핑 + 정책 + 메모를 모두 보고 LLM 이 root + sub-modules 를 한 번에 작성.
    # 결정론적 generators 는 더 이상 호출되지 않음 (코드는 남겨둠 — rollback 용).
    pipeline_log.append("Step 2/5: Terraform 코드 생성 (LLM codegen, 단일 호출)")
    t0 = time.time()
    try:
        root, modules, codegen_log = generate_terraform_code(
            ctx,
            strategy=strategy,
            llm_deployment=llm_deployment,
            azure_openai_endpoint=azure_openai_endpoint,
        )
        for line in codegen_log:
            pipeline_log.append(f"  · {line}")
        pipeline_log.append(
            f"  • {time.time() - t0:.1f}s — root({len(root.files)} files) + {len(modules)} modules"
        )
    except Exception as e:
        pipeline_log.append(f"  • LLM codegen 실패 (해당 plan 의 terraform 미생성): {e}")
        # Surface a minimal empty plan rather than crashing the whole pipeline;
        # validate step will mark validation_passed=False.
        root = TerraformModule(name="root", files={}, inputs=[], outputs=[])
        modules = []

    # ── Step 3.5: Policy compliance LLM pass (modify/append 정책 반영) ──
    field_ops = (ctx.policy_constraints or {}).get("field_operations") or []
    if field_ops:
        pipeline_log.append(f"Step 3.5/5: Policy compliance LLM pass ({len(field_ops)}개 operation)")
        t0 = time.time()
        try:
            from .policy_compliance import apply_policy_compliance
            patch_out, patch_log = apply_policy_compliance(
                root_module=root,
                modules=modules,
                field_operations=field_ops,
                llm_deployment=llm_deployment,
                azure_openai_endpoint=azure_openai_endpoint,
            )
            for line in patch_log:
                pipeline_log.append(f"  · {line}")
            if patch_out and patch_out.patches:
                from .policy_compliance import _apply_patches_to_modules
                n = _apply_patches_to_modules(patch_out.patches, root, modules)
                pipeline_log.append(f"  • {time.time() - t0:.1f}s — {n}개 파일에 정책 반영")
            else:
                pipeline_log.append(f"  • {time.time() - t0:.1f}s — patch 없음")
        except Exception as e:
            pipeline_log.append(f"  • Policy compliance pass 실패 (코드 변경 없음): {e}")

    # ── Step 4: Validate ──────────────────────────────────────────
    validation_passed = False
    validation_log: List[str] = []
    if not skip_validation:
        pipeline_log.append("Step 4/5: terraform fmt + init + validate")
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="tf-validate-") as td:
            work = Path(td)
            try:
                write_modules_to_disk(work, root, modules)
                result = validate_terraform(work)
                validation_passed = bool(result["passed"])
                validation_log = list(result["log"])
                pipeline_log.append(f"  • {time.time() - t0:.1f}s — passed={validation_passed}, skipped={result.get('skipped', False)}")
            except Exception as e:
                validation_log.append(f"검증 중 오류: {e}")
                pipeline_log.append(f"  • 오류: {e}")
    else:
        pipeline_log.append("Step 4/5: 검증 건너뜀 (skip_validation=True)")

    # ── Step 5: Data migrations (LLM) ─────────────────────────────
    # 각 매핑된 AWS 데이터 리소스 (S3/RDS/Dynamo/Redis 등) 에 대한 shell
    # migration 스크립트를 LLM 이 직접 작성.  rule-based fallback 은 LLM
    # 실패 시에만 사용.
    pipeline_log.append("Step 5/5: 데이터 이전 스크립트 (LLM)")
    t0 = time.time()
    data_migs: List[DataMigrationScript] = []
    try:
        from .data_migration import generate_data_migration_scripts as gen_dm
        data_migs, dm_log = gen_dm(
            ctx,
            llm_deployment=llm_deployment,
            azure_openai_endpoint=azure_openai_endpoint,
        )
        for line in dm_log:
            pipeline_log.append(f"  · {line}")
        pipeline_log.append(f"  • {time.time() - t0:.1f}s — {len(data_migs)}개 스크립트 (LLM)")
    except Exception as e:
        pipeline_log.append(f"  • LLM 실패, rule-based fallback: {e}")
        data_migs = _generate_data_migrations(ctx)
        pipeline_log.append(f"  • fallback → {len(data_migs)}개 스크립트")

    pipeline_log.append(f"전체 소요: {time.time() - started:.1f}s")

    plan = MigrationPlanV2(
        summary=strategy.summary,
        assessment=strategy.assessment,
        waves=list(strategy.waves),
        risks=list(strategy.risks),
        open_questions=list(strategy.open_questions),
        terraform_modules=modules,
        root_module=root,
        data_migrations=data_migs,
        validation_passed=validation_passed,
        validation_log=validation_log,
        pipeline_log=pipeline_log,
    )
    return plan.model_dump()
