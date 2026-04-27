"""Migration planning API — async jobs and saved outputs (same pattern as promotion Run Analysis)."""

import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse


# Accept only sensible Terraform / HCL / docs filenames.  Reject paths so the
# model can't walk out of the run directory (``../`` etc.).
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.\-]*$")
_ALLOWED_TF_SUFFIXES = (".tf", ".tfvars", ".tfvars.json", ".hcl", ".md", ".txt")
_ALLOWED_EXACT_NAMES = {".gitignore", ".terraform-version"}


def _sanitize_tf_filename(name: str) -> str:
    """Return a safe flat filename for a Terraform artifact, or '' if invalid."""
    if not name:
        return ""
    name = name.strip().replace("\\", "/").split("/")[-1]  # drop any directory parts
    if not _SAFE_FILENAME_RE.match(name):
        return ""
    if name in _ALLOWED_EXACT_NAMES:
        return name
    if not name.endswith(_ALLOWED_TF_SUFFIXES):
        return ""
    return name


def _write_terraform_artifacts(run_dir: Path, files: List[Dict[str, Any]]) -> List[str]:
    """Materialise ``plan.terraform`` into ``<run_dir>/terraform/`` on disk.

    Returns the list of files that were actually written (sanitized names).
    """
    if not files:
        return []
    tf_dir = run_dir / "terraform"
    tf_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    seen: set[str] = set()
    for f in files:
        name = _sanitize_tf_filename(str(f.get("filename") or ""))
        if not name or name in seen:
            continue
        content = f.get("content") or ""
        (tf_dir / name).write_text(content, encoding="utf-8")
        written.append(name)
        seen.add(name)
    return written

_agent_cls = None


def _get_agent_class():
    global _agent_cls
    if _agent_cls is None:
        from app.agent_module.migration_agent import MigrationAgent

        _agent_cls = MigrationAgent
    return _agent_cls


BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_ROOT = BACKEND_ROOT / "outputs"
# Working copies for `terraform apply` are kept in a hidden directory so
# uvicorn's `--reload` watcher (which excludes dot-dirs by default) doesn't
# restart the server every time terraform writes state files.
DEPLOYMENTS_ROOT = BACKEND_ROOT / ".deployments"

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

_deploys: Dict[str, Dict[str, Any]] = {}
_deploys_lock = threading.Lock()


def _run_migration_worker(job_id: str, params: Dict[str, Any]) -> None:
    import os

    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    try:
        MigrationAgent = _get_agent_class()
        endpoint = params.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
        llm_deployment = params.get("llm_deployment") or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required")

        agent = MigrationAgent(
            llm_deployment=llm_deployment,
            azure_openai_endpoint=endpoint,
        )
        result = agent.run(
            aws_resource_spec=params.get("aws_resource_spec", ""),
            target_azure_region=params.get("target_azure_region", "eastus"),
            migration_goals=params.get("migration_goals", ""),
            output_format=params.get("output_format", "json"),
            azure_mappings=params.get("azure_mappings") or None,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = OUTPUTS_ROOT / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        summary_path = output_dir / "agent_output.md"
        summary_path.write_text(result.get("final_output", "<no final_output>"), encoding="utf-8")

        log_path = json_path = None
        if execution_log := result.get("execution_log"):
            log_path = output_dir / "execution_log.txt"
            log_path.write_text("\n\n---\n\n".join(str(x) for x in execution_log), encoding="utf-8")

        tf_files_written: List[str] = []
        if json_data := result.get("json_data"):
            json_path = output_dir / "agent_output.json"
            json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")
            tf_files_written = _write_terraform_artifacts(output_dir, json_data.get("terraform") or [])

        with _jobs_lock:
            _jobs[job_id].update({
                "status": "completed",
                "result": {
                    "final_output": result.get("final_output"),
                    "json_data": result.get("json_data"),
                    "execution_log": result.get("execution_log"),
                    "artifacts": {
                        "output_dir": str(output_dir),
                        "summary_path": str(summary_path),
                        "execution_log_path": str(log_path) if log_path else "",
                        "json_path": str(json_path) if json_path else "",
                        "run_id": timestamp,
                        "terraform_dir": str(output_dir / "terraform") if tf_files_written else "",
                        "terraform_files": tf_files_written,
                    },
                },
                "completed_at": time.time(),
            })
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id].update({
                "status": "failed",
                "error": str(e),
                "completed_at": time.time(),
            })


router = APIRouter(prefix="/migration", tags=["migration"])


@router.post("/run")
def start_migration_plan(request: dict, background_tasks: BackgroundTasks):
    """Start a migration planning job."""
    import os

    aws_resource_spec = (request.get("aws_resource_spec") or "").strip()
    if not aws_resource_spec:
        raise HTTPException(status_code=400, detail="aws_resource_spec is required")

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise HTTPException(
            status_code=503,
            detail="AZURE_OPENAI_ENDPOINT must be set in .env or environment.",
        )

    azure_mappings = request.get("azure_mappings")
    if azure_mappings is not None and not isinstance(azure_mappings, list):
        raise HTTPException(
            status_code=400, detail="azure_mappings must be a list if provided"
        )

    job_id = str(uuid.uuid4())
    params = {
        "aws_resource_spec": aws_resource_spec,
        "target_azure_region": request.get("target_azure_region", "eastus"),
        "migration_goals": request.get("migration_goals", ""),
        "output_format": request.get("output_format", "json"),
        "llm_deployment": request.get("llm_deployment"),
        "endpoint": request.get("endpoint"),
        "azure_mappings": azure_mappings or [],
    }

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "pending",
            "params": params,
            "result": None,
            "error": None,
            "started_at": time.time(),
            "completed_at": None,
        }

    background_tasks.add_task(_run_migration_worker, job_id, params)
    return {"job_id": job_id, "status": "pending"}


@router.get("/run/{job_id}")
def get_migration_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    out: Dict[str, Any] = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "completed" and job.get("result"):
        out["result"] = job["result"]
    if job["status"] == "failed" and job.get("error"):
        out["error"] = job["error"]
    return out


_mapping_agent_cls = None


def _get_mapping_agent_class():
    global _mapping_agent_cls
    if _mapping_agent_cls is None:
        from app.agent_module.mapping_agent import AzureMappingAgent

        _mapping_agent_cls = AzureMappingAgent
    return _mapping_agent_cls


@router.post("/azure-mapping")
def map_resources_to_azure(request: dict):
    """Map selected AWS resources to candidate Azure targets (sync LLM call).

    Request body:
        {
          "resources": [ {service, type, name, id, arn, region, tags}, ... ],
          "target_azure_region": "eastus"   // optional
        }
    Response:
        { "mappings": [ {aws_key, azure_service, azure_resource_type, rationale, ...} ] }
    """
    import os

    raw_resources = request.get("resources") or []
    if not isinstance(raw_resources, list) or len(raw_resources) == 0:
        raise HTTPException(
            status_code=400, detail="'resources' must be a non-empty list"
        )
    if len(raw_resources) > 200:
        raise HTTPException(
            status_code=400,
            detail=f"Too many resources ({len(raw_resources)}); cap is 200.",
        )

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise HTTPException(
            status_code=503,
            detail="AZURE_OPENAI_ENDPOINT must be set in .env or environment.",
        )

    AzureMappingAgent = _get_mapping_agent_class()
    agent = AzureMappingAgent(
        llm_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        azure_openai_endpoint=endpoint,
    )
    result = agent.run(
        resources=raw_resources,
        target_azure_region=str(request.get("target_azure_region") or "eastus"),
        source_aws_region=str(request.get("source_aws_region") or ""),
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return {
        "mappings": result.get("mappings") or [],
        "execution_log": result.get("execution_log") or [],
    }


@router.get("/active-job")
def get_active_job():
    with _jobs_lock:
        for jid, job in _jobs.items():
            if job["status"] in ("pending", "running"):
                return {"job_id": jid, "status": job["status"]}
    return {"job_id": None, "status": None}


@router.get("/outputs")
def list_outputs():
    if not OUTPUTS_ROOT.exists():
        return {"runs": []}
    run_dirs = sorted(
        [p for p in OUTPUTS_ROOT.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    runs = []
    for d in run_dirs[:50]:
        has_md = (d / "agent_output.md").exists()
        has_json = (d / "agent_output.json").exists()
        tf_dir = d / "terraform"
        tf_files = sorted(p.name for p in tf_dir.iterdir()) if tf_dir.is_dir() else []
        runs.append({
            "run_id": d.name,
            "has_summary": has_md,
            "has_json": has_json,
            "has_terraform": len(tf_files) > 0,
            "terraform_file_count": len(tf_files),
        })
    return {"runs": runs}


@router.get("/outputs/{run_id}")
def get_output(run_id: str):
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    result: Dict[str, Any] = {"run_id": run_id}
    md_path = run_dir / "agent_output.md"
    json_path = run_dir / "agent_output.json"
    log_path = run_dir / "execution_log.txt"
    if md_path.exists():
        result["summary"] = md_path.read_text(encoding="utf-8")
    if json_path.exists():
        try:
            result["json_data"] = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            result["json_data"] = None
    if log_path.exists():
        result["execution_log"] = log_path.read_text(encoding="utf-8")

    tf_dir = run_dir / "terraform"
    if tf_dir.is_dir():
        result["terraform_files"] = sorted(p.name for p in tf_dir.iterdir() if p.is_file())
    return result


@router.get("/outputs/{run_id}/terraform.zip")
def download_terraform_zip(run_id: str):
    """Stream the generated Terraform module as a zip archive."""
    run_dir = OUTPUTS_ROOT / run_id
    tf_dir = run_dir / "terraform"
    if not tf_dir.is_dir():
        raise HTTPException(status_code=404, detail="No terraform module for this run")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(tf_dir.iterdir()):
            if p.is_file():
                zf.write(p, arcname=p.name)
    buffer.seek(0)

    filename = f"azure-terraform-{run_id}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/outputs/{run_id}/terraform/{filename}")
def get_terraform_file(run_id: str, filename: str):
    """Return a single Terraform file's raw content (for preview / copy)."""
    safe = _sanitize_tf_filename(filename)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = OUTPUTS_ROOT / run_id / "terraform" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return {"filename": safe, "content": path.read_text(encoding="utf-8")}


# ---------------------------------------------------------------------------
# In-app Terraform deploy (replaces the zip-download CLI workflow)
# ---------------------------------------------------------------------------

_DEPLOY_ALLOWED_ACTIONS = {"apply", "destroy"}


def _run_cli(cmd: List[str], timeout: float = 15.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": "binary not found", "returncode": 127}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timed out", "returncode": -1}


def _detect_terraform() -> Dict[str, Any]:
    res = _run_cli(["terraform", "version", "-json"])
    if not res["ok"]:
        return {"installed": False, "version": "", "error": res["stderr"] or "terraform not found"}
    version = ""
    try:
        version = json.loads(res["stdout"]).get("terraform_version", "")
    except Exception:
        m = re.search(r"v([0-9]+\.[0-9]+\.[0-9]+)", res["stdout"])
        if m:
            version = m.group(1)
    return {"installed": True, "version": version}


def _detect_azure() -> Dict[str, Any]:
    """Probe `az` CLI: is it installed, who is signed in, what subs are visible?"""
    ver = _run_cli(["az", "version"])
    if not ver["ok"]:
        return {
            "installed": False,
            "signed_in": False,
            "subscriptions": [],
            "default_subscription_id": "",
            "error": ver["stderr"] or "az not found",
        }
    subs_res = _run_cli(
        ["az", "account", "list", "--query", "[].{id:id,name:name,isDefault:isDefault,tenantId:tenantId}", "-o", "json"],
        timeout=20.0,
    )
    if not subs_res["ok"]:
        return {
            "installed": True,
            "signed_in": False,
            "subscriptions": [],
            "default_subscription_id": "",
            "error": (subs_res["stderr"] or subs_res["stdout"] or "").strip()
            or "az login required",
        }
    try:
        subs = json.loads(subs_res["stdout"] or "[]")
    except Exception:
        subs = []
    default_id = next((s.get("id", "") for s in subs if s.get("isDefault")), "")
    return {
        "installed": True,
        "signed_in": len(subs) > 0,
        "subscriptions": subs,
        "default_subscription_id": default_id,
    }


@router.get("/deploy/preflight")
def deploy_preflight():
    """Check that terraform + az are usable from the backend host."""
    return {
        "terraform": _detect_terraform(),
        "azure": _detect_azure(),
    }


def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id or ""):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    return run_id


def _sync_terraform_workdir(run_id: str) -> Path:
    """Copy generated .tf files into the persistent deploy working dir.

    State files (`terraform.tfstate`, `.terraform/`) stay put across calls so
    a subsequent `destroy` can find resources created by `apply`.
    """
    src = OUTPUTS_ROOT / run_id / "terraform"
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="No terraform module for this run")
    work = DEPLOYMENTS_ROOT / run_id
    work.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, work / f.name)
    return work


def _append_log(deploy_id: str, line: str) -> None:
    with _deploys_lock:
        d = _deploys.get(deploy_id)
        if d is not None:
            d["logs"].append(line)


def _set_step(deploy_id: str, step: str) -> None:
    with _deploys_lock:
        d = _deploys.get(deploy_id)
        if d is not None:
            d["current_step"] = step


def _stream_subprocess(deploy_id: str, label: str, cmd: List[str], cwd: Path, env: Dict[str, str]) -> int:
    _set_step(deploy_id, label)
    _append_log(deploy_id, f"")
    _append_log(deploy_id, f"$ [{label}] {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        _append_log(deploy_id, f"ERROR: {exc}")
        return 127
    with _deploys_lock:
        d = _deploys.get(deploy_id)
        if d is not None:
            d["pid"] = proc.pid
    assert proc.stdout is not None
    for raw in proc.stdout:
        _append_log(deploy_id, raw.rstrip("\n"))
    return proc.wait()


def _run_deploy_worker(deploy_id: str, run_id: str, action: str, subscription_id: str, tenant_id: str) -> None:
    try:
        with _deploys_lock:
            _deploys[deploy_id]["status"] = "running"
            _deploys[deploy_id]["started_at"] = time.time()

        work = _sync_terraform_workdir(run_id)

        env = os.environ.copy()
        if subscription_id:
            env["ARM_SUBSCRIPTION_ID"] = subscription_id
        if tenant_id:
            env["ARM_TENANT_ID"] = tenant_id
        env["TF_IN_AUTOMATION"] = "1"
        env["TF_INPUT"] = "0"

        if subscription_id:
            _append_log(deploy_id, f"Using Azure subscription: {subscription_id}")
        _append_log(deploy_id, f"Working directory: {work}")

        if action == "apply":
            steps = [
                ("init", ["terraform", "init", "-input=false", "-no-color"]),
                ("plan", ["terraform", "plan", "-input=false", "-no-color", "-out=tfplan"]),
                ("apply", ["terraform", "apply", "-input=false", "-no-color", "-auto-approve", "tfplan"]),
            ]
        else:
            steps = [
                ("init", ["terraform", "init", "-input=false", "-no-color"]),
                ("destroy", ["terraform", "destroy", "-input=false", "-no-color", "-auto-approve"]),
            ]

        for label, cmd in steps:
            rc = _stream_subprocess(deploy_id, label, cmd, work, env)
            if rc != 0:
                raise RuntimeError(f"step '{label}' failed with exit code {rc}")

        _append_log(deploy_id, "")
        _append_log(deploy_id, "✓ Deployment finished successfully.")
        with _deploys_lock:
            _deploys[deploy_id].update({
                "status": "succeeded",
                "current_step": "done",
                "completed_at": time.time(),
            })
    except Exception as exc:
        _append_log(deploy_id, "")
        _append_log(deploy_id, f"✗ Deployment failed: {exc}")
        with _deploys_lock:
            _deploys[deploy_id].update({
                "status": "failed",
                "error": str(exc),
                "completed_at": time.time(),
            })


@router.post("/outputs/{run_id}/deploy")
def start_deploy(run_id: str, request: dict):
    run_id = _safe_run_id(run_id)
    src = OUTPUTS_ROOT / run_id / "terraform"
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="No terraform module for this run")

    action = (request.get("action") or "apply").strip().lower()
    if action not in _DEPLOY_ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(_DEPLOY_ALLOWED_ACTIONS)}")

    subscription_id = (request.get("subscription_id") or "").strip()
    tenant_id = (request.get("tenant_id") or "").strip()

    # Block concurrent deploys for the same run_id — terraform state isn't
    # safe to operate on from two workers at once.
    with _deploys_lock:
        for did, d in _deploys.items():
            if d.get("run_id") == run_id and d["status"] in ("pending", "running"):
                raise HTTPException(
                    status_code=409,
                    detail=f"A {d['action']} is already running for this run (deploy_id={did}).",
                )

        deploy_id = str(uuid.uuid4())
        _deploys[deploy_id] = {
            "deploy_id": deploy_id,
            "run_id": run_id,
            "action": action,
            "subscription_id": subscription_id,
            "status": "pending",
            "current_step": "queued",
            "logs": [],
            "error": None,
            "started_at": None,
            "completed_at": None,
            "pid": None,
        }

    thread = threading.Thread(
        target=_run_deploy_worker,
        args=(deploy_id, run_id, action, subscription_id, tenant_id),
        daemon=True,
    )
    thread.start()

    return {"deploy_id": deploy_id, "status": "pending", "action": action, "run_id": run_id}


@router.get("/deploy/{deploy_id}")
def get_deploy_status(deploy_id: str, since: int = 0):
    """Poll deploy status. Pass `since` to receive only new log lines."""
    with _deploys_lock:
        d = _deploys.get(deploy_id)
        if not d:
            raise HTTPException(status_code=404, detail="Deploy not found")
        all_logs = d["logs"]
        total = len(all_logs)
        if since < 0:
            since = 0
        if since > total:
            since = total
        new_lines = all_logs[since:]
        return {
            "deploy_id": deploy_id,
            "run_id": d["run_id"],
            "action": d["action"],
            "status": d["status"],
            "current_step": d.get("current_step", ""),
            "subscription_id": d.get("subscription_id", ""),
            "error": d.get("error"),
            "started_at": d.get("started_at"),
            "completed_at": d.get("completed_at"),
            "log_offset": since,
            "log_total": total,
            "log_lines": new_lines,
        }


@router.get("/outputs/{run_id}/deploys")
def list_deploys_for_run(run_id: str):
    run_id = _safe_run_id(run_id)
    with _deploys_lock:
        items = [
            {
                "deploy_id": did,
                "run_id": d["run_id"],
                "action": d["action"],
                "status": d["status"],
                "current_step": d.get("current_step", ""),
                "started_at": d.get("started_at"),
                "completed_at": d.get("completed_at"),
            }
            for did, d in _deploys.items()
            if d["run_id"] == run_id
        ]
    items.sort(key=lambda x: (x.get("started_at") or 0), reverse=True)
    return {"deploys": items}
