"""Phase 3: Deploy & Migrate — structured multi-phase deployment.

Splits the legacy single-call ``terraform init+plan+apply`` flow into
explicit phases so the user can:
  • see a Plan Preview before changes are made
  • approve / cancel before apply
  • track Data Migration script completion
  • validate that Azure resources were actually created

Phases:
    preflight     → terraform / az / session checks
    plan_running  → terraform init + plan in progress
    plan_ready    → user must approve before apply
    apply_running → terraform apply in progress
    applied       → terraform apply succeeded
    data_migration→ user runs data scripts (RDS/S3/etc.) manually
    validating    → list created Azure resources
    complete      → all done
    failed        → any phase failed
    cancelled     → user cancelled
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/deploy/v2", tags=["deploy-v2"])

# ── Phase constants ─────────────────────────────────────────────
PHASE_PREFLIGHT      = "preflight"
PHASE_PLAN_RUNNING   = "plan_running"
PHASE_PLAN_READY     = "plan_ready"
PHASE_APPLY_RUNNING  = "apply_running"
PHASE_AUTO_FIXING    = "auto_fixing"    # NEW: AI가 자율적으로 코드 수정 중
PHASE_APPLY_FAILED   = "apply_failed"   # auto-fix 도 실패하거나 사용자 액션 필요
PHASE_APPLIED        = "applied"
PHASE_DATA_MIGRATION = "data_migration"
PHASE_VALIDATING     = "validating"
PHASE_COMPLETE       = "complete"
PHASE_FAILED         = "failed"
PHASE_CANCELLED      = "cancelled"

# Auto-fix loop limits — single shot per user click; user picks next action.
MAX_AUTO_FIX_ATTEMPTS = int(os.getenv("DEPLOY_MAX_AUTO_FIX", "1"))

# In-memory deploy state
_deploys: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()

BACKEND_ROOT     = Path(__file__).resolve().parent.parent.parent
OUTPUTS_ROOT     = BACKEND_ROOT / "outputs"
DEPLOYMENTS_ROOT = BACKEND_ROOT / ".deployments"


# ── helpers ─────────────────────────────────────────────────────

def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id or ""):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    return run_id


def _get_deploy(deploy_id: str) -> Dict[str, Any]:
    with _lock:
        d = _deploys.get(deploy_id)
    if not d:
        raise HTTPException(status_code=404, detail="Deploy not found")
    return d


def _append_log(deploy_id: str, line: str) -> None:
    with _lock:
        d = _deploys.get(deploy_id)
        if d is not None:
            d["logs"].append(line)


def _set_phase(deploy_id: str, phase: str, *, error: Optional[str] = None) -> None:
    with _lock:
        d = _deploys.get(deploy_id)
        if d is None:
            return
        d["phase"] = phase
        if error:
            d["error"] = error
        if phase in (PHASE_COMPLETE, PHASE_FAILED, PHASE_CANCELLED):
            d["completed_at"] = time.time()


def _deploy_workdir(run_id: str, deploy_id: str) -> Path:
    """Per-deploy working directory.

    1 Plan : N Deploys — each deploy gets its own isolated folder so state,
    cache, and patches don't leak between deploys.  Folder name embeds the
    Plan id for human readability:
        .deployments/<run_id>__<deploy_id_short>/
    """
    short = deploy_id[:8] if deploy_id else "unknown"
    return DEPLOYMENTS_ROOT / f"{run_id}__{short}"


def _sync_terraform_workdir(run_id: str, deploy_id: str) -> Path:
    """Copy outputs/<run_id>/terraform/ → .deployments/<run_id>__<deploy_id>/.

    Each Deploy gets its own isolated folder (always starts fresh — there is
    no soft-sync mode anymore since per-deploy folders give clean isolation
    by construction).  Returns the deploy's work path.
    """
    src = OUTPUTS_ROOT / run_id / "terraform"
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="No terraform module for this run")
    work = _deploy_workdir(run_id, deploy_id)

    # Always create fresh — wipe any half-baked artefacts from a previous
    # attempt that happened to use the same deploy_id (very unlikely with
    # uuid4, but keeps behavior deterministic).
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    # Copy root files
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, work / f.name)
    # Copy modules/ subdirectory if present
    src_modules = src / "modules"
    if src_modules.is_dir():
        dst_modules = work / "modules"
        if dst_modules.exists():
            shutil.rmtree(dst_modules)
        shutil.copytree(src_modules, dst_modules)
    return work


def _wipe_deploy_workdir(run_id: str, deploy_id: str) -> Dict[str, Any]:
    """Hard-reset: delete this deploy's folder entirely."""
    work = _deploy_workdir(run_id, deploy_id)
    if not work.exists():
        return {"existed": False, "path": str(work)}
    shutil.rmtree(work)
    return {"existed": True, "path": str(work)}


def _stream_subprocess(deploy_id: str, label: str, cmd: List[str], cwd: Path, env: Dict[str, str]) -> int:
    _append_log(deploy_id, "")
    _append_log(deploy_id, f"$ [{label}] {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except FileNotFoundError as e:
        _append_log(deploy_id, f"ERROR: {e}")
        return 127
    output_lines: List[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        _append_log(deploy_id, line)
        output_lines.append(line)
    rc = proc.wait()
    return rc


def _build_env(deploy: Dict[str, Any]) -> Dict[str, str]:
    """Build ARM_* environment variables from session scope (Phase 0)."""
    env = os.environ.copy()
    scope = deploy.get("scope") or {}
    if sub := scope.get("azure_subscription_id"):
        env["ARM_SUBSCRIPTION_ID"] = sub
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    return env


# ── preflight ──────────────────────────────────────────────────

def _run_preflight(deploy_id: str) -> Dict[str, Any]:
    """Check terraform binary, az CLI, session scope."""
    result: Dict[str, Any] = {"ok": True, "checks": []}

    # terraform
    tf_path = shutil.which("terraform")
    result["checks"].append({
        "name": "terraform 바이너리",
        "ok": bool(tf_path),
        "detail": tf_path or "PATH 에 terraform이 없습니다",
    })
    if not tf_path:
        result["ok"] = False

    # session scope (Azure subscription)
    deploy = _get_deploy(deploy_id)
    scope = deploy.get("scope") or {}
    sub_id = scope.get("azure_subscription_id")
    result["checks"].append({
        "name": "Azure Subscription",
        "ok": bool(sub_id),
        "detail": sub_id or "(scope 미설정 — Connect 단계에서 확인)",
    })
    if not sub_id:
        result["ok"] = False

    # terraform module exists
    src = OUTPUTS_ROOT / deploy["run_id"] / "terraform"
    result["checks"].append({
        "name": "Terraform 모듈",
        "ok": src.is_dir(),
        "detail": str(src),
    })
    if not src.is_dir():
        result["ok"] = False

    return result


# ── plan ────────────────────────────────────────────────────────

def _run_plan(deploy_id: str, *, resync: bool = True) -> None:
    """Run terraform init + plan for this deploy.

    resync=True (default): copy fresh tree from outputs/ first (wipes any edits).
    resync=False: reuse the current workdir contents — used when caller wants
    to preserve in-place code edits (e.g. destroy-restart with patched code).
    """
    try:
        deploy = _get_deploy(deploy_id)
        if resync:
            work = _sync_terraform_workdir(deploy["run_id"], deploy_id)
            _append_log(deploy_id, f"📁 작업 디렉토리: {work.name}")
        else:
            work = Path(deploy["work_dir"])
            _append_log(deploy_id, f"📁 작업 디렉토리 (코드 보존): {work.name}")
        with _lock:
            _deploys[deploy_id]["work_dir"] = str(work)
        env = _build_env(deploy)

        # User-supplied variable overrides → terraform.tfvars.json
        from app.services.tfvars import write_tfvars_json
        if deploy.get("tfvars"):
            tfvars_path = write_tfvars_json(work, deploy["tfvars"])
            if tfvars_path:
                _append_log(deploy_id, f"변수 override 적용: {tfvars_path.name} ({len(deploy['tfvars'])}개)")

        _set_phase(deploy_id, PHASE_PLAN_RUNNING)
        _append_log(deploy_id, f"Working directory: {work}")

        rc = _stream_subprocess(
            deploy_id, "init",
            ["terraform", "init", "-input=false", "-no-color"],
            work, env,
        )
        if rc != 0:
            _set_phase(deploy_id, PHASE_FAILED, error=f"terraform init exit code {rc}")
            return

        rc = _stream_subprocess(
            deploy_id, "plan",
            ["terraform", "plan", "-input=false", "-no-color", "-out=tfplan"],
            work, env,
        )
        if rc != 0:
            _set_phase(deploy_id, PHASE_FAILED, error=f"terraform plan exit code {rc}")
            return

        # Capture the plan summary as text (last 100 lines of logs since plan started)
        with _lock:
            plan_logs = _deploys[deploy_id]["logs"][-200:]
        with _lock:
            _deploys[deploy_id]["plan_output"] = "\n".join(plan_logs)

        _set_phase(deploy_id, PHASE_PLAN_READY)
        _append_log(deploy_id, "")
        _append_log(deploy_id, "✓ Plan 완료 — 자동으로 apply 진행")
        # 사용자 승인 게이트 없이 곧바로 apply 진행 — preflight 단계에 plan 까지 묶음
        _run_apply(deploy_id)
    except Exception as e:
        _set_phase(deploy_id, PHASE_FAILED, error=str(e))
        _append_log(deploy_id, f"ERROR: {e}")


# ── apply ───────────────────────────────────────────────────────

def _run_auto_fix(deploy_id: str, attempt: int) -> bool:
    """Run the tool-calling fix agent against the workdir.

    The agent autonomously inspects files, makes edits, and validates with
    terraform — streaming each action to the deploy log.

    Returns True if the agent signalled `done` (caller should retry apply),
    False on `give_up` / errors / iteration exhaustion.
    """
    try:
        from app.agent_module.v2.fix_agent_tools import run_fix_agent

        deploy = _get_deploy(deploy_id)
        work = Path(deploy["work_dir"]).resolve()
        # Generous tail — the agent reads the most recent N log lines as the error.
        error_log = "\n".join(deploy["logs"][-300:])

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

        _append_log(deploy_id, "")
        _append_log(deploy_id, f"━━━ AI 자동 수정 #{attempt}/{MAX_AUTO_FIX_ATTEMPTS}  (tool-calling 모드) ━━━")

        if not endpoint:
            _append_log(deploy_id, "✗ AZURE_OPENAI_ENDPOINT 미설정 — 자동 수정 불가")
            return False

        # Stream each tool call to the deploy log so the user sees the agent thinking.
        ICONS = {
            "list_files":    "📁",
            "read_file":     "📖",
            "edit_file":     "✏",
            "write_file":    "✍",
            "run_terraform": "🔨",
            "run_az":        "☁️",
            "done":          "✓",
            "give_up":       "✗",
        }

        def _on_action(act: Dict[str, Any]) -> None:
            tool = act.get("tool", "")
            args = act.get("args") or {}
            preview = act.get("result_preview", "")
            icon = ICONS.get(tool, "•")
            # Build a compact one-liner per action
            arg_str = ""
            if tool in ("read_file", "write_file", "edit_file"):
                arg_str = args.get("path", "")
            elif tool == "run_terraform":
                arg_str = args.get("command", "")
            elif tool == "done":
                arg_str = (args.get("summary") or "")[:80]
            elif tool == "give_up":
                arg_str = (args.get("reason") or "")[:60]
            line = f"  {icon} {tool}({arg_str})"
            if preview:
                line += f"  →  {preview}"
            _append_log(deploy_id, line)

        result = run_fix_agent(
            work_dir=work,
            error_log=error_log,
            llm_deployment=deployment,
            azure_openai_endpoint=endpoint,
            on_action=_on_action,
        )

        # Stash a slim summary so UI can show the user's "AI fix" panel
        with _lock:
            _deploys[deploy_id]["latest_ai_fix"] = {
                "diagnosis":   result.get("summary", ""),
                "confidence":  result.get("outcome", ""),
                "user_action": result.get("user_action") or "",
                "fixes":       [],   # not used in tool-calling mode (agent edited directly)
                "iterations":  result.get("iterations", 0),
                "actions":     result.get("actions") or [],
            }

        outcome = result.get("outcome", "")
        _append_log(deploy_id, f"━━━ 결과: {outcome}  ({result.get('iterations', 0)} iterations) ━━━")
        _append_log(deploy_id, f"요약: {result.get('summary', '')[:300]}")

        if outcome == "done":
            return True

        if outcome == "give_up" and result.get("user_action"):
            _append_log(deploy_id, f"사용자 액션 필요: {result['user_action']}")

        return False
    except Exception as e:
        _append_log(deploy_id, f"✗ 자동 수정 실패: {e}")
        logger.exception("Auto-fix failed for deploy %s", deploy_id)
        return False


def _run_auto_rollback(deploy_id: str, work: Path, env: Dict[str, str], *, apply_error: str) -> None:
    """terraform refresh → destroy → state cleanup → re-plan.

    Called automatically right after apply fails when the deploy has
    auto_rollback=True (the default).  Gets the deploy back to a clean
    PHASE_PLAN_READY so subsequent attempts don't accumulate broken state.

    If destroy itself fails, the deploy is **quarantined** — apply_failed
    with a flag the UI surfaces.  Quarantined deploys should be abandoned
    and a new deploy created from the same Plan.
    """
    # 1) terraform refresh — sync state ↔ Azure reality.  Most "destroy can't
    #    delete X because it never existed / mismatch" errors come from drift,
    #    so we proactively refresh first.  Refresh failure is non-fatal.
    _append_log(deploy_id, "  · refresh — state ↔ Azure 실제 리소스 동기화")
    _stream_subprocess(
        deploy_id, "refresh",
        ["terraform", "apply", "-refresh-only", "-auto-approve", "-input=false", "-no-color"],
        work, env,
    )

    # 2) terraform destroy — clean up partial deployment
    _append_log(deploy_id, "  · destroy — 부분 생성된 리소스 정리")
    rc = _stream_subprocess(
        deploy_id, "destroy",
        ["terraform", "destroy", "-input=false", "-no-color", "-auto-approve"],
        work, env,
    )
    if rc != 0:
        # State too broken to recover automatically — quarantine.
        with _lock:
            _deploys[deploy_id]["quarantined"] = True
        _set_phase(
            deploy_id, PHASE_APPLY_FAILED,
            error=f"{apply_error}; 자동 롤백 destroy 도 실패 (exit {rc})",
        )
        _append_log(deploy_id, f"✗ 자동 롤백 destroy 실패 (exit {rc}) — 이 deploy 폴더는 격리됩니다")
        _append_log(deploy_id, "→ 새 deploy 를 시작하거나 셸로 직접 정리 후 새로 시작하세요")
        return

    # 3) state/cache cleanup, keep .tf code intact
    for stale in (".terraform.lock.hcl", "tfplan"):
        p = work / stale
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    for tfstate in work.glob("terraform.tfstate*"):
        tfstate.unlink()

    _append_log(deploy_id, "✓ 자동 롤백 완료 — 깨끗한 상태에서 재계획")
    _run_plan(deploy_id, resync=False)


def _run_apply(deploy_id: str, *, use_tfplan: bool = True, fix_attempt: int = 0) -> None:
    """Run terraform apply.

    On retry (use_tfplan=False, after user edits or applies AI fix):
      • re-runs terraform init (catches new providers/modules)
      • runs terraform plan -detailed-exitcode FIRST → catches "fix is no-op"
        early (e.g., user patched a default that the caller overrides)
      • only proceeds to apply when plan actually has changes (exit code 2)

    On apply failure: sets PHASE_APPLY_FAILED.  AI diagnosis is NOT triggered
    automatically — the user explicitly initiates it from the UI via /ai-fix.
    """
    _ = fix_attempt   # retained for backward compat with retry-apply callers
    try:
        deploy = _get_deploy(deploy_id)
        work = Path(deploy["work_dir"])
        env = _build_env(deploy)

        # Clear stale AI diagnosis from a previous failed cycle so the panel
        # doesn't show old "AI 진단" content when this apply also fails.
        with _lock:
            _deploys[deploy_id]["latest_ai_fix"] = None

        _set_phase(deploy_id, PHASE_APPLY_RUNNING)

        if not use_tfplan:
            # Re-init in case providers/modules changed
            rc = _stream_subprocess(
                deploy_id, "init (retry)",
                ["terraform", "init", "-input=false", "-no-color", "-upgrade=false"],
                work, env,
            )
            if rc != 0:
                _set_phase(deploy_id, PHASE_APPLY_FAILED, error=f"terraform init (retry) exit code {rc}")
                _append_log(deploy_id, "✗ init 실패 — 코드를 다시 확인하세요")
                return

            # Plan first — detect if the fix actually changes anything.
            # detailed-exitcode: 0=no changes, 1=error, 2=changes
            rc = _stream_subprocess(
                deploy_id, "plan (verify fix)",
                ["terraform", "plan", "-input=false", "-no-color", "-detailed-exitcode", "-out=tfplan"],
                work, env,
            )
            if rc == 0:
                # No changes — user's edits didn't alter the planned state.
                _append_log(deploy_id, "")
                _append_log(deploy_id, "⚠ plan 결과: 변경 사항 없음 — 수정이 실제 plan에 반영되지 않았습니다")
                _set_phase(
                    deploy_id, PHASE_APPLY_FAILED,
                    error="수정이 효과적이지 않습니다 (plan에 변경 없음).",
                )
                _append_log(deploy_id, "→ root main.tf 호출부 / module 사용처를 확인하세요")
                return
            elif rc != 2:
                # rc=1 (error) — likely syntax error from a bad patch
                _append_log(deploy_id, "")
                _append_log(deploy_id, f"✗ terraform plan 실패 (exit {rc})")
                _set_phase(deploy_id, PHASE_APPLY_FAILED, error=f"terraform plan exit code {rc}")
                return

            # rc == 2: changes detected, proceed to apply
            _append_log(deploy_id, "")
            _append_log(deploy_id, "✓ plan 통과 — 변경 사항이 감지되어 apply 진행")

        cmd = (
            ["terraform", "apply", "-input=false", "-no-color", "-auto-approve", "tfplan"]
            if use_tfplan
            else ["terraform", "apply", "-input=false", "-no-color", "-auto-approve", "tfplan"]
            # On retry we already produced a fresh tfplan above, so use it
        )
        rc = _stream_subprocess(deploy_id, "apply" if use_tfplan else "apply (retry)", cmd, work, env)
        if rc != 0:
            _append_log(deploy_id, "")
            _append_log(deploy_id, f"✗ apply 실패 (exit code {rc})")
            apply_error = f"terraform apply exit code {rc}"

            # Stash the failure reason so the resulting plan_ready (after auto-rollback)
            # or apply_failed panel can surface it.
            with _lock:
                _deploys[deploy_id]["last_apply_failure"] = {
                    "exit_code": rc,
                    "at":        time.time(),
                    "log_tail":  "\n".join(_deploys[deploy_id]["logs"][-60:]),
                }

            if deploy.get("auto_rollback", True):
                _append_log(deploy_id, "↻ 자동 롤백 시작 — refresh → destroy → re-plan")
                _run_auto_rollback(deploy_id, work, env, apply_error=apply_error)
            else:
                _set_phase(deploy_id, PHASE_APPLY_FAILED, error=apply_error)
                _append_log(deploy_id, "→ 자동 롤백 OFF — UI에서 'AI 진단' 또는 직접 코드 편집 후 재시도")
            return

        _append_log(deploy_id, "")
        _append_log(deploy_id, "✓ Terraform apply 완료")

        # Order: apply → validate → (data migration if scripts) → complete
        # Validation first so the user sees what was actually created before
        # being asked to run any data migration scripts.
        _run_validation(deploy_id)
    except Exception as e:
        _set_phase(deploy_id, PHASE_FAILED, error=str(e))
        _append_log(deploy_id, f"ERROR: {e}")


# ── destroy + restart ───────────────────────────────────────────

def _run_destroy_restart(
    deploy_id: str,
    *,
    preserve_code: bool = False,
    pending_fixes: Optional[List[Dict[str, str]]] = None,
) -> None:
    """terraform destroy → optionally apply pending file patches → re-plan.

    Order matters here:
      1. ``terraform destroy`` runs against the **original on-disk code**
         (the same code that was used to apply, so it matches the state).
         Applying patches BEFORE destroy can break destroy when the patched
         code references resources differently from what's in state.
      2. After destroy succeeds, apply ``pending_fixes`` to disk (if any).
      3. Clean state/cache (preserve_code=True) or wipe workdir entirely
         (preserve_code=False, factory reset — pending_fixes is ignored).
      4. ``terraform init + plan`` with the patched code → PHASE_PLAN_READY.
    """
    try:
        deploy = _get_deploy(deploy_id)
        work = Path(deploy["work_dir"])
        env = _build_env(deploy)

        with _lock:
            _deploys[deploy_id]["latest_ai_fix"] = None
        _set_phase(deploy_id, PHASE_APPLY_RUNNING)

        _append_log(deploy_id, "")
        _append_log(deploy_id, "🗑 terraform destroy — 부분 배포된 리소스 정리 (원본 코드 기준)")
        rc = _stream_subprocess(
            deploy_id, "destroy",
            ["terraform", "destroy", "-input=false", "-no-color", "-auto-approve"],
            work, env,
        )
        if rc != 0:
            _set_phase(deploy_id, PHASE_APPLY_FAILED, error=f"terraform destroy exit code {rc}")
            _append_log(deploy_id, "✗ destroy 실패 — 셸에서 직접 정리하세요")
            return

        if not preserve_code:
            _append_log(deploy_id, "✓ destroy 완료 — 워크 디렉토리 초기화 후 처음부터 재계획")
            _wipe_deploy_workdir(deploy["run_id"], deploy_id)
            _run_plan(deploy_id, resync=True)
            return

        _append_log(deploy_id, "✓ destroy 완료 — 코드 수정 보존 + state/cache 정리")

        # Apply pending file patches AFTER destroy (so destroy used original code)
        if pending_fixes:
            written = 0
            for entry in pending_fixes:
                rel = (entry.get("filename") or "").strip()
                content = entry.get("content")
                if not rel or content is None:
                    continue
                # Strip common prefixes the LLM sometimes prepends
                rel = rel.lstrip("./")
                if rel.startswith("terraform/"):
                    rel = rel[len("terraform/"):]
                target = _safe_relative_path(rel, work)
                if not target:
                    _append_log(deploy_id, f"  ⚠ 스킵 (안전하지 않은 경로): {rel}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written += 1
            _append_log(deploy_id, f"✓ destroy 후 패치 {written}개 파일 적용")

        # Wipe state files / lock / cache, keep .tf files
        for stale in (".terraform", ".terraform.lock.hcl", "tfplan"):
            p = work / stale
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        for tfstate in work.glob("terraform.tfstate*"):
            tfstate.unlink()
        _run_plan(deploy_id, resync=False)
    except Exception as e:
        _set_phase(deploy_id, PHASE_FAILED, error=str(e))
        _append_log(deploy_id, f"ERROR: {e}")


# ── validation ──────────────────────────────────────────────────

def _run_validation(deploy_id: str) -> None:
    """List resources in the target subscription / RG to confirm what was created.

    Uses Phase-0 session credential when available, otherwise falls back to
    ``DefaultAzureCredential`` (az login → managed identity → SP env vars).
    """
    try:
        _set_phase(deploy_id, PHASE_VALIDATING)
        deploy = _get_deploy(deploy_id)
        scope = deploy.get("scope") or {}
        sub_id = scope.get("azure_subscription_id")
        session_id = deploy.get("session_id")

        _append_log(deploy_id, "")
        _append_log(deploy_id, f"Azure 리소스 검증 (subscription={sub_id})")

        validated = {"resources": [], "by_type": {}, "error": None}
        try:
            from azure.mgmt.resource import ResourceManagementClient

            cred = None
            if session_id:
                try:
                    from app.routers.credentials import _get
                    sess = _get(session_id)
                    cred = (sess.get("azure") or {}).get("credential")
                except Exception:
                    cred = None

            if cred is None:
                # Fallback when session is gone (e.g., backend reloaded mid-deploy)
                from azure.identity import DefaultAzureCredential
                cred = DefaultAzureCredential()
                _append_log(deploy_id, "  (세션 없음 → DefaultAzureCredential 사용)")

            client = ResourceManagementClient(cred, sub_id)
            for rg in client.resource_groups.list():
                # Filter to RGs we created (heuristic: managed_by tag)
                tags = rg.tags or {}
                if tags.get("managed_by") != "cloud-transformation-agent":
                    continue
                _append_log(deploy_id, f"  ResourceGroup: {rg.name}")
                resources = list(client.resources.list_by_resource_group(rg.name))
                for r in resources:
                    rt = r.type
                    validated["resources"].append({
                        "name": r.name, "type": rt, "location": r.location,
                        "resource_group": rg.name,
                    })
                    validated["by_type"][rt] = validated["by_type"].get(rt, 0) + 1
                    _append_log(deploy_id, f"    ✓ {rt}/{r.name}")
        except Exception as e:
            validated["error"] = str(e)
            _append_log(deploy_id, f"검증 부분 실패: {e}")

        with _lock:
            _deploys[deploy_id]["validation"] = validated
            scripts = _deploys[deploy_id].get("data_migration_scripts") or []

        _append_log(deploy_id, "")
        _append_log(deploy_id, f"✓ 검증 완료 — Azure 리소스 {len(validated['resources'])}개 확인")

        # Validation done.  If we have data-migration scripts, hand off to the
        # user-driven data migration step; otherwise we're complete.
        if scripts:
            _set_phase(deploy_id, PHASE_DATA_MIGRATION)
            _append_log(deploy_id, f"📦 데이터 이전 스크립트 {len(scripts)}개 — 사용자 확인 대기")
        else:
            _set_phase(deploy_id, PHASE_COMPLETE)
            _append_log(deploy_id, "✓ 마이그레이션 완료 (데이터 이전 스크립트 없음)")
    except Exception as e:
        _set_phase(deploy_id, PHASE_FAILED, error=str(e))
        _append_log(deploy_id, f"ERROR: {e}")


# ── public endpoints ────────────────────────────────────────────

@router.post("/reset/{deploy_id}")
def reset_workdir(deploy_id: str):
    """Hard-reset: wipe this deploy's working folder (state, cache, AI patches)."""
    deploy = _get_deploy(deploy_id)
    return _wipe_deploy_workdir(deploy["run_id"], deploy_id)


@router.post("/scope-check")
def scope_check(body: Dict[str, Any] = Body(...)):
    """Pre-flight feasibility check for a target Azure scope.

    Combines policy + SKU availability + compute quota for the target
    subscription/region against the resources described in the Plan's
    terraform code.  Doesn't create a deploy — runs against
    ``outputs/{run_id}/terraform/`` directly.

    Body:
        { "run_id": "...", "subscription_id": "...", "region": "..." }
    """
    run_id = _safe_run_id(body.get("run_id", ""))
    sub_id = (body.get("subscription_id") or "").strip()
    region = (body.get("region") or "").strip()
    if not sub_id or not region:
        raise HTTPException(status_code=400, detail="subscription_id and region are required")

    src = OUTPUTS_ROOT / run_id / "terraform"
    if not src.is_dir():
        raise HTTPException(status_code=404, detail=f"No terraform module for run_id {run_id}")

    from app.services.scope_check import check_scope
    return check_scope(work_dir=src, subscription_id=sub_id, region=region)


@router.post("/start")
def start_deploy(body: dict):
    """Create a new structured deployment.

    1 Plan : N Deploys — every call creates a brand new ``.deployments/{run_id}__{deploy_id}/``
    folder copied from ``outputs/{run_id}/terraform/``, fully isolated from
    any previous deploy of the same Plan.

    Body:
        {
          "run_id":     "20260507_123456",
          "session_id": "<uuid>",                       // preferred
          "azure_subscription_id": "...", "azure_region": "...",   // fallback if session is gone
          "tfvars":     { ... }                          // optional override
        }
    """
    run_id = _safe_run_id(body.get("run_id", ""))
    session_id = (body.get("session_id") or "").strip()
    tfvars = body.get("tfvars") or None
    auto_rollback = bool(body.get("auto_rollback", True))   # default ON
    if tfvars is not None and not isinstance(tfvars, dict):
        raise HTTPException(status_code=400, detail="tfvars must be a dict if provided")

    # 1. Try active session
    scope: Optional[Dict[str, Any]] = None
    session_valid = False
    if session_id:
        try:
            from app.routers.credentials import _get
            sess = _get(session_id)
            scope = sess.get("scope")
            if scope:
                session_valid = True
        except HTTPException:
            session_valid = False

    # 2. Fallback to body-supplied scope (e.g., after backend reload)
    if not scope:
        body_sub    = (body.get("azure_subscription_id") or "").strip()
        body_region = (body.get("azure_region") or "").strip()
        if body_sub:
            scope = {
                "aws_account_id":           body.get("aws_account_id") or "",
                "aws_region":               body.get("aws_region") or "",
                "azure_subscription_id":    body_sub,
                "azure_subscription_name":  body.get("azure_subscription_name") or "",
                "azure_region":             body_region,
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="No active session and no fallback Azure subscription_id provided. "
                       "Reconnect via the Connect step or pass azure_subscription_id in the body.",
            )

    # Read data migration scripts from the run's plan output
    scripts: List[Dict[str, Any]] = []
    json_path = OUTPUTS_ROOT / run_id / "agent_output.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            v2 = data.get("v2") or {}
            scripts = v2.get("data_migrations") or []
        except Exception:
            scripts = []

    deploy_id = str(uuid.uuid4())
    with _lock:
        _deploys[deploy_id] = {
            "deploy_id":               deploy_id,
            "run_id":                  run_id,
            "session_id":              session_id,
            "scope":                   scope,
            "tfvars":                  tfvars,            # user variable overrides
            "auto_rollback":           auto_rollback,     # apply 실패 시 자동 destroy + re-plan
            "quarantined":             False,             # destroy 도 실패한 경우 True
            "last_apply_failure":      None,
            "phase":                   PHASE_PREFLIGHT,
            "started_at":              time.time(),
            "completed_at":            None,
            "logs":                    [],
            "preflight_result":        None,
            "plan_output":             "",
            "data_migration_scripts":  scripts,
            "data_migration_status":   [
                {"index": i, "title": s.get("title"), "resource": s.get("resource"), "completed": False, "completed_at": None}
                for i, s in enumerate(scripts)
            ],
            "validation":              None,
            "error":                   None,
            "work_dir":                None,
        }

    # Run preflight synchronously (it's fast); if OK, kick off plan in background
    pf = _run_preflight(deploy_id)
    with _lock:
        _deploys[deploy_id]["preflight_result"] = pf

    if not pf["ok"]:
        _set_phase(deploy_id, PHASE_FAILED, error="Preflight 실패")
        _append_log(deploy_id, "Preflight 실패 — 자세한 내용은 preflight_result 확인")
        for c in pf["checks"]:
            mark = "✓" if c["ok"] else "✗"
            _append_log(deploy_id, f"  {mark} {c['name']}: {c['detail']}")
        return {"deploy_id": deploy_id, "phase": PHASE_FAILED, "preflight": pf}

    threading.Thread(target=_run_plan, args=(deploy_id,), daemon=True).start()
    return {"deploy_id": deploy_id, "phase": PHASE_PLAN_RUNNING, "preflight": pf}


@router.get("/list")
def list_all_deploys():
    """All deploys in memory, newest first.  The Deploy page uses this as its
    default landing view."""
    items = []
    with _lock:
        for did, d in _deploys.items():
            items.append({
                "deploy_id":     did,
                "run_id":        d.get("run_id"),
                "phase":         d.get("phase"),
                "started_at":    d.get("started_at"),
                "completed_at":  d.get("completed_at"),
                "error":         d.get("error"),
                "log_total":     len(d.get("logs") or []),
            })
    items.sort(key=lambda x: x.get("started_at") or 0, reverse=True)
    return {"deploys": items}


@router.get("/by-run/{run_id}")
def list_deploys_for_run(run_id: str):
    """All Deploys created for a given Plan (run_id), newest first.

    Lets the UI honor the 1-Plan : N-Deploys relationship — user can resume an
    in-flight deploy or start a fresh one from the same Plan.
    """
    rid = _safe_run_id(run_id)
    items = []
    with _lock:
        for did, d in _deploys.items():
            if d.get("run_id") != rid:
                continue
            items.append({
                "deploy_id":     did,
                "run_id":        d.get("run_id"),
                "phase":         d.get("phase"),
                "started_at":    d.get("started_at"),
                "completed_at":  d.get("completed_at"),
                "error":         d.get("error"),
                "log_total":     len(d.get("logs") or []),
            })
    items.sort(key=lambda x: x.get("started_at") or 0, reverse=True)
    return {"run_id": rid, "deploys": items}


@router.get("/{deploy_id}")
def get_status(deploy_id: str, since: int = 0):
    """Polling endpoint — current phase, new log lines since `since`."""
    deploy = _get_deploy(deploy_id)
    with _lock:
        all_logs = deploy["logs"]
        total = len(all_logs)
    if since < 0:
        since = 0
    if since > total:
        since = total
    new_lines = all_logs[since:]
    return {
        "deploy_id":              deploy_id,
        "run_id":                 deploy["run_id"],
        "phase":                  deploy["phase"],
        "started_at":             deploy["started_at"],
        "completed_at":           deploy.get("completed_at"),
        "error":                  deploy.get("error"),
        "preflight_result":       deploy.get("preflight_result"),
        "plan_output":            deploy.get("plan_output", "") if deploy["phase"] in (PHASE_PLAN_READY, PHASE_APPLY_RUNNING, PHASE_APPLY_FAILED, PHASE_APPLIED, PHASE_DATA_MIGRATION, PHASE_VALIDATING, PHASE_COMPLETE) else "",
        "data_migration_status":  deploy.get("data_migration_status") or [],
        "validation":             deploy.get("validation"),
        "latest_ai_fix":          deploy.get("latest_ai_fix"),
        "auto_rollback":          deploy.get("auto_rollback", True),
        "quarantined":            deploy.get("quarantined", False),
        "last_apply_failure":     deploy.get("last_apply_failure"),
        "log_offset":             since,
        "log_total":              total,
        "log_lines":              new_lines,
    }


@router.post("/{deploy_id}/approve")
def approve_plan(deploy_id: str):
    """User approves the Plan Preview and triggers terraform apply."""
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_PLAN_READY:
        raise HTTPException(status_code=409, detail=f"Cannot approve in phase '{deploy['phase']}'")

    threading.Thread(target=_run_apply, args=(deploy_id,), daemon=True).start()
    return {"phase": PHASE_APPLY_RUNNING}


@router.post("/{deploy_id}/cancel")
def cancel_deploy(deploy_id: str):
    """Cancel a deploy that's still in pre-apply phases."""
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] in (PHASE_APPLY_RUNNING, PHASE_VALIDATING):
        raise HTTPException(status_code=409, detail="Cannot cancel mid-apply")
    _set_phase(deploy_id, PHASE_CANCELLED)
    _append_log(deploy_id, "")
    _append_log(deploy_id, "✗ 사용자 취소")
    return {"phase": PHASE_CANCELLED}


@router.post("/{deploy_id}/data-migration/{idx}/complete")
def mark_data_migration_complete(deploy_id: str, idx: int):
    """Mark a data-migration script as completed by the user."""
    deploy = _get_deploy(deploy_id)
    statuses = deploy.get("data_migration_status") or []
    if idx < 0 or idx >= len(statuses):
        raise HTTPException(status_code=404, detail="Script index out of range")

    with _lock:
        _deploys[deploy_id]["data_migration_status"][idx]["completed"] = True
        _deploys[deploy_id]["data_migration_status"][idx]["completed_at"] = time.time()
        all_done = all(s["completed"] for s in _deploys[deploy_id]["data_migration_status"])

    _append_log(deploy_id, f"✓ 데이터 이전 #{idx+1} 완료: {statuses[idx].get('title','')}")

    if all_done and deploy["phase"] == PHASE_DATA_MIGRATION:
        _append_log(deploy_id, "✓ 모든 데이터 이전 스크립트 완료")
        _set_phase(deploy_id, PHASE_COMPLETE)
        _append_log(deploy_id, "✓ 마이그레이션 완료")

    return {"completed": True, "all_done": all_done}


@router.post("/{deploy_id}/skip-data-migration")
def skip_data_migration(deploy_id: str):
    """Skip remaining data migration scripts — mark deploy complete."""
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_DATA_MIGRATION:
        raise HTTPException(status_code=409, detail=f"Cannot skip in phase '{deploy['phase']}'")
    _append_log(deploy_id, "데이터 이전 단계 건너뜀 (사용자 결정)")
    _set_phase(deploy_id, PHASE_COMPLETE)
    _append_log(deploy_id, "✓ 마이그레이션 완료")
    return {"phase": PHASE_COMPLETE}


# ── apply 실패 → 수정 → 재시도 흐름 ──────────────────────────────

def _read_all_tf_files(work: Path) -> Dict[str, str]:
    """Read every .tf / .tfvars / .md file inside the working directory."""
    files: Dict[str, str] = {}
    for p in work.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in (".tf", ".tfvars", ".md"):
            continue
        # Skip generated artifacts
        rel = p.relative_to(work)
        first_part = rel.parts[0]
        if first_part in (".terraform",):
            continue
        files[str(rel)] = p.read_text(encoding="utf-8")
    return files


def _safe_relative_path(rel: str, work: Path) -> Optional[Path]:
    """Resolve ``rel`` inside ``work`` defensively (rejects path traversal).

    Both ``work`` and the resolved target are passed through ``.resolve()`` so
    macOS symlinks (``/var`` → ``/private/var``) don't cause false rejections.
    """
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    work_resolved = work.resolve()
    full = (work_resolved / rel).resolve()
    try:
        full.relative_to(work_resolved)
    except ValueError:
        return None
    if full.suffix not in (".tf", ".tfvars", ".md", ".json"):
        return None
    return full


@router.get("/{deploy_id}/files")
def list_deploy_files(deploy_id: str):
    """Return the current Terraform files in the deploy's working directory."""
    deploy = _get_deploy(deploy_id)
    if not deploy.get("work_dir"):
        raise HTTPException(status_code=404, detail="No working directory yet")
    work = Path(deploy["work_dir"])
    if not work.is_dir():
        raise HTTPException(status_code=404, detail="Working directory missing")
    return {"files": _read_all_tf_files(work)}


@router.post("/{deploy_id}/ai-fix")
def ai_fix(deploy_id: str, body: Optional[Dict[str, Any]] = Body(None)):
    """Ask the LLM to diagnose the apply failure and propose a patch.

    Body (optional):
        { "strategy": "patch_and_retry" | "destroy_and_apply" }

    The user picks the strategy in the UI:
      • patch_and_retry  — keep current resources, fix incrementally (default)
      • destroy_and_apply — assume destroy first, fix for clean re-apply

    Does NOT apply the fix automatically — the response is shown to the user
    for review.  Use ``/{deploy_id}/apply-fix`` to actually write files.
    """
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_APPLY_FAILED:
        raise HTTPException(status_code=409, detail=f"AI fix only available in apply_failed phase (current: {deploy['phase']})")

    strategy = ((body or {}).get("strategy") or "patch_and_retry").strip()
    if strategy not in ("patch_and_retry", "destroy_and_apply"):
        raise HTTPException(status_code=400, detail=f"unknown strategy: {strategy}")

    work = Path(deploy["work_dir"])
    files = _read_all_tf_files(work)
    error_log = "\n".join(deploy["logs"][-150:])

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    if not endpoint:
        raise HTTPException(status_code=503, detail="AZURE_OPENAI_ENDPOINT is required for AI fix")

    from app.agent_module.v2.fix_agent import fix_terraform_error
    result = fix_terraform_error(
        error_log=error_log,
        files=files,
        llm_deployment=deployment,
        azure_openai_endpoint=endpoint,
        strategy=strategy,
    )
    payload = result.model_dump()

    # Stash on the deploy so the frontend can re-display without re-asking
    with _lock:
        _deploys[deploy_id]["latest_ai_fix"] = payload

    mode_label = "destroy 전제" if strategy == "destroy_and_apply" else "현재 state 유지"
    _append_log(deploy_id, f"AI 진단 ({mode_label}): {payload['diagnosis']}")
    if payload.get("fixes"):
        _append_log(deploy_id, f"AI 제안: {len(payload['fixes'])}개 파일 수정 (검토 후 적용 가능)")
    if payload.get("commands"):
        _append_log(deploy_id, f"AI 제안 CLI: {len(payload['commands'])}개 명령 (셸에서 실행 가능)")
    return payload


@router.post("/{deploy_id}/apply-fix")
def apply_fix(deploy_id: str, body: dict):
    """Write the user-approved fix to disk.

    Body:
        { "files": [ {"filename": "main.tf", "content": "..."}, ... ] }
    """
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_APPLY_FAILED:
        raise HTTPException(status_code=409, detail=f"Cannot apply fix in phase '{deploy['phase']}'")
    work = Path(deploy["work_dir"]).resolve()    # always resolve (handles macOS /var↔/private/var)

    files = body.get("files") or []
    if not isinstance(files, list) or not files:
        raise HTTPException(status_code=400, detail="files (list) is required")

    written: List[str] = []
    skipped: List[Dict[str, str]] = []
    for f in files:
        rel = (f.get("filename") or "").strip()
        # The AI sometimes prefixes paths with './' or 'terraform/' — strip them.
        if rel.startswith("./"):
            rel = rel[2:]
        if rel.startswith("terraform/"):
            rel = rel[len("terraform/"):]
        content = f.get("content")
        if not rel or content is None:
            skipped.append({"filename": rel or "(empty)", "reason": "비어있음"})
            continue
        full = _safe_relative_path(rel, work)
        if full is None:
            skipped.append({"filename": rel, "reason": "허용되지 않는 경로 (절대경로/.. 포함/지원안되는 확장자)"})
            continue
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            written.append(str(full.relative_to(work)))
        except Exception as e:
            skipped.append({"filename": rel, "reason": f"write 실패: {e}"})

    _append_log(deploy_id, f"파일 패치 적용: {len(written)}개 written, {len(skipped)}개 skipped")
    for w in written:
        _append_log(deploy_id, f"  ✓ {w}")
    for s in skipped:
        _append_log(deploy_id, f"  ✗ {s['filename']}  ({s['reason']})")

    if not written:
        _append_log(deploy_id, "⚠ 적용된 파일이 없습니다 — retry 해도 동일한 에러가 날 가능성이 높습니다")

    return {"written": written, "skipped": skipped}


@router.post("/{deploy_id}/retry-apply")
def retry_apply(deploy_id: str):
    """Re-run terraform apply after the user has fixed code.

    Uses 'plan + apply' (not the saved tfplan, which is stale after edits).
    """
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_APPLY_FAILED:
        raise HTTPException(status_code=409, detail=f"Cannot retry in phase '{deploy['phase']}'")

    _append_log(deploy_id, "")
    _append_log(deploy_id, "↻ apply 재시도 (코드 수정 적용)")
    threading.Thread(target=_run_apply, args=(deploy_id,), kwargs={"use_tfplan": False}, daemon=True).start()
    return {"phase": PHASE_APPLY_RUNNING}


@router.post("/{deploy_id}/continue-auto-fix")
def continue_auto_fix(deploy_id: str):
    """User opt-in: run another N rounds of the autonomous AI fix loop.

    Resets the per-deploy fix_attempt counter so the agent gets a fresh
    MAX_AUTO_FIX_ATTEMPTS budget and re-enters _run_apply.
    """
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] != PHASE_APPLY_FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot continue auto-fix in phase '{deploy['phase']}'",
        )
    _append_log(deploy_id, "")
    _append_log(deploy_id, "↻ 사용자 요청: 자동 수정 1회 추가 시도")
    threading.Thread(
        target=_run_apply,
        args=(deploy_id,),
        kwargs={"use_tfplan": False, "fix_attempt": 0},
        daemon=True,
    ).start()
    return {"phase": PHASE_AUTO_FIXING}


@router.post("/{deploy_id}/exec")
def exec_in_workdir(deploy_id: str, body: Dict[str, Any] = Body(...)):
    """Run an arbitrary shell command in the deploy's working directory.

    No allow-list / no token filter — pipes, redirects, and any binary on
    PATH all work.  This is a developer tool that runs locally on the user's
    own machine; the user is trusted.  Output is trimmed and the call has a
    120s timeout.
    """
    deploy = _get_deploy(deploy_id)
    cmd = (body.get("cmd") or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="cmd is empty")

    if not deploy.get("work_dir"):
        raise HTTPException(status_code=409, detail="작업 디렉토리가 아직 없습니다 — 배포를 먼저 시작하세요")
    work = Path(deploy["work_dir"]).resolve()
    if not work.is_dir():
        raise HTTPException(status_code=409, detail=f"작업 디렉토리가 존재하지 않음: {work}")

    try:
        proc = subprocess.run(
            cmd, cwd=str(work), capture_output=True, text=True,
            timeout=120, check=False, shell=True,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        if len(out) > 16000:
            out = out[:16000] + f"\n...[잘림 — 총 {len(out):,} chars]"
        if len(err) > 4000:
            err = err[-4000:]
        return {
            "command":   cmd,
            "exit_code": proc.returncode,
            "stdout":    out,
            "stderr":    err,
        }
    except subprocess.TimeoutExpired:
        return {"command": cmd, "exit_code": -1, "stdout": "", "stderr": "120초 타임아웃"}


@router.post("/{deploy_id}/destroy-restart")
def destroy_and_restart(deploy_id: str, body: Optional[Dict[str, Any]] = Body(None)):
    """Run terraform destroy then re-plan.

    Body:
        {
          "preserve_code": false,        // default — factory reset
          "preserve_code": true,         // keep workdir code (only clean state/cache)
          "pending_fixes": [             // applied AFTER destroy, before plan
            {"filename": "main.tf", "content": "..."},
            ...
          ]
        }

    pending_fixes is the way to apply AI patches with destroy_and_apply
    strategy: destroy runs against ORIGINAL code (matches state), patches
    are written afterwards, then plan picks up the patched code.
    """
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] not in (
        PHASE_APPLY_FAILED, PHASE_APPLIED, PHASE_COMPLETE,
        PHASE_DATA_MIGRATION, PHASE_VALIDATING, PHASE_PLAN_READY,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"phase '{deploy['phase']}' 에서는 destroy-restart 를 실행할 수 없습니다",
        )
    if not deploy.get("work_dir"):
        raise HTTPException(status_code=409, detail="작업 디렉토리가 아직 없음 — destroy 할 게 없음")
    body = body or {}
    preserve_code = bool(body.get("preserve_code"))
    pending_fixes = body.get("pending_fixes") or []
    if not isinstance(pending_fixes, list):
        raise HTTPException(status_code=400, detail="pending_fixes must be a list")
    threading.Thread(
        target=_run_destroy_restart,
        args=(deploy_id,),
        kwargs={"preserve_code": preserve_code, "pending_fixes": pending_fixes},
        daemon=True,
    ).start()
    return {"phase": PHASE_APPLY_RUNNING}


@router.post("/{deploy_id}/abandon")
def abandon_deploy(deploy_id: str):
    """Give up on a failed deploy — terminal state."""
    deploy = _get_deploy(deploy_id)
    if deploy["phase"] not in (PHASE_APPLY_FAILED, PHASE_PLAN_READY):
        raise HTTPException(status_code=409, detail=f"Cannot abandon in phase '{deploy['phase']}'")
    _set_phase(deploy_id, PHASE_FAILED, error=deploy.get("error") or "사용자가 수정 포기")
    _append_log(deploy_id, "✗ 사용자가 배포를 포기했습니다")
    return {"phase": PHASE_FAILED}
