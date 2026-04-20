"""Migration planning API — async jobs and saved outputs (same pattern as promotion Run Analysis)."""

import io
import json
import re
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

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


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

    job_id = str(uuid.uuid4())
    params = {
        "aws_resource_spec": aws_resource_spec,
        "target_azure_region": request.get("target_azure_region", "eastus"),
        "migration_goals": request.get("migration_goals", ""),
        "output_format": request.get("output_format", "json"),
        "llm_deployment": request.get("llm_deployment"),
        "endpoint": request.get("endpoint"),
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
