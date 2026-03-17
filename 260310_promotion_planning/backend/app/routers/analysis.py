"""Run Analysis API - migrated from agentic-analytics Streamlit."""

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

# Lazy import to avoid loading heavy deps when not using analysis
_agent_module = None
_simulator_module = None

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_ROOT = BACKEND_ROOT / "outputs"
DEFAULT_DATASET = "data/synthetic_promotions_snacks_bev.csv"


def _resolve_dataset_path(dataset_path: str) -> str:
    """Resolve dataset path to absolute for agent/executor."""
    p = Path(dataset_path)
    if not p.is_absolute():
        p = BACKEND_ROOT / dataset_path
    return str(p.resolve())
DEFAULT_PERSONA_PROMPTS = {
    "promo_generator": "Maximize volume uplift while maintaining positive ROI",
}

# In-memory job store (for single-process deployment)
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _get_agent_module():
    global _agent_module
    if _agent_module is None:
        from app.agent_module.agent import AnalyticsAgent
        _agent_module = AnalyticsAgent
    return _agent_module


def _get_simulator():
    global _simulator_module
    if _simulator_module is None:
        from app.agent_module.simulator.simulation import simulate_agent_output_json
        _simulator_module = simulate_agent_output_json
    return _simulator_module


def _run_agent_worker(job_id: str, params: Dict[str, Any]) -> None:
    """Background worker that runs the analytics agent."""
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    try:
        AnalyticsAgent = _get_agent_module()
        dataset_path = _resolve_dataset_path(params.get("dataset_path", DEFAULT_DATASET))
        instruction = params.get("instruction", "")
        num_promotions = params.get("num_promotions", 15)
        region_filter = params.get("region_filter", ["All"])
        min_discount = params.get("min_discount", 10)
        output_format = "json_converter" if params.get("output_format") == "json" else "plain_text"
        llm_deployment = params.get("llm_deployment", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
        endpoint = params.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
        embedding_deployment = params.get("embedding_deployment") or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required for run analysis")

        full_instruction = (
            f"Business objective: {instruction}\n"
            f"Region: {region_filter}\n"
            f"Minimum discount allowed: {min_discount}%\n"
            f"Number of promotions required: {num_promotions}"
        )

        agent = AnalyticsAgent(
            dataset_path=dataset_path,
            llm_deployment=llm_deployment,
            azure_openai_endpoint=endpoint,
            embedding_deployment=embedding_deployment,
        )
        result = agent.run(
            enable_search=False,
            instruction=full_instruction,
            output_format=output_format,
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

        if json_data := result.get("json_data"):
            json_path = output_dir / "agent_output.json"
            json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

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


router = APIRouter(prefix="/analysis", tags=["analysis"])


class RunAnalysisRequest:
    def __init__(self, data: dict):
        self.instruction = data.get("instruction", "")
        self.num_promotions = int(data.get("num_promotions", 15))
        self.min_discount = int(data.get("min_discount", 10))
        self.region_filter = data.get("region_filter", ["All"])
        self.output_format = data.get("output_format", "json")
        self.dataset_path = data.get("dataset_path", DEFAULT_DATASET)


@router.post("/run")
def start_run_analysis(request: dict, background_tasks: BackgroundTasks):
    """Start a run analysis job. Returns job_id for polling."""
    req = RunAnalysisRequest(request)
    if not req.instruction.strip():
        raise HTTPException(status_code=400, detail="instruction is required")

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise HTTPException(
            status_code=503,
            detail="Run analysis requires AZURE_OPENAI_ENDPOINT. Set it in .env or environment.",
        )

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "pending",
            "params": {
                "instruction": req.instruction,
                "num_promotions": req.num_promotions,
                "min_discount": req.min_discount,
                "region_filter": req.region_filter,
                "output_format": req.output_format,
                "dataset_path": req.dataset_path,
            },
            "result": None,
            "error": None,
            "started_at": time.time(),
            "completed_at": None,
        }

    background_tasks.add_task(_run_agent_worker, job_id, _jobs[job_id]["params"])
    return {"job_id": job_id, "status": "pending"}


@router.get("/run/{job_id}")
def get_run_status(job_id: str):
    """Poll for run analysis job status and result."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    out = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "completed" and job.get("result"):
        out["result"] = job["result"]
    if job["status"] == "failed" and job.get("error"):
        out["error"] = job["error"]
    return out


@router.get("/active-job")
def get_active_job():
    """Return the currently running/pending job, if any."""
    with _jobs_lock:
        for jid, job in _jobs.items():
            if job["status"] in ("pending", "running"):
                return {"job_id": jid, "status": job["status"]}
    return {"job_id": None, "status": None}


@router.get("/outputs")
def list_outputs():
    """List saved analysis runs (from outputs folder)."""
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
        runs.append({
            "run_id": d.name,
            "has_summary": has_md,
            "has_json": has_json,
        })
    return {"runs": runs}


@router.get("/outputs/{run_id}")
def get_output(run_id: str):
    """Get details of a saved run."""
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    result = {"run_id": run_id}
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
    return result


class SimulateRequest:
    def __init__(self, data: dict):
        self.run_id = data.get("run_id")
        self.dataset_path = data.get("dataset_path", DEFAULT_DATASET)


@router.post("/simulate")
def run_simulation(request: dict):
    """Run simulation/scoring on a saved agent_output.json."""
    req = SimulateRequest(request)
    if not req.run_id:
        raise HTTPException(status_code=400, detail="run_id is required")

    json_path = OUTPUTS_ROOT / req.run_id / "agent_output.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"agent_output.json not found for run {req.run_id}")

    base = Path(__file__).resolve().parent.parent.parent
    dataset_path = Path(req.dataset_path)
    if not dataset_path.is_absolute():
        dataset_path = base / req.dataset_path
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {req.dataset_path}")

    try:
        simulate = _get_simulator()
        df_scored, summary = simulate(
            agent_output_json_path=json_path,
            dataset_csv_path=dataset_path,
        )
        display_cols = [
            c
            for c in [
                "promo_event_id",
                "market",
                "retailer",
                "sku_id",
                "discount_depth",
                "promo_investment",
                "pred_incremental_volume",
                "pred_incr_profit",
                "pred_roi",
            ]
            if c in df_scored.columns
        ]
        scored_list = df_scored[display_cols].sort_values(by="pred_roi", ascending=False)
        records = scored_list.where(scored_list.notna(), None).to_dict(orient="records")
        return {
            "summary": {
                "num_candidates_in": summary.num_candidates_in,
                "num_candidates_scored": summary.num_candidates_scored,
                "pred_roi_min": summary.pred_roi_min,
                "pred_roi_max": summary.pred_roi_max,
                "pred_roi_positive_count": summary.pred_roi_positive_count,
            },
            "scored_promotions": records,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")
