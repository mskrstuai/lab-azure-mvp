"""Executor service - sandboxed Python execution for agent. Migrated from agentic-analytics."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import secrets

# Optional Azure deps for non-local env
try:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient
except ImportError:
    DefaultAzureCredential = None
    BlobClient = None

security = HTTPBasic()


def verify_basic_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    username = os.environ.get("EXECUTOR_USERNAME")
    password = os.environ.get("EXECUTOR_PASSWORD")
    if not username or not password:
        raise HTTPException(
            status_code=500,
            detail="Basic authentication is not configured. Set EXECUTOR_USERNAME and EXECUTOR_PASSWORD.",
        )
    valid_user = secrets.compare_digest(credentials.username or "", username)
    valid_pass = secrets.compare_digest(credentials.password or "", password)
    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(dependencies=[Depends(verify_basic_auth)])


class ExecutionRequest(BaseModel):
    code: str
    dataset_uri: str
    timeout_sec: int = 120
    execution_id: str


@app.post("/execute")
async def execute_code(request: ExecutionRequest):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        script_path = temp_path / f"script_{request.execution_id}.py"
        data_path = temp_path / f"data_{request.execution_id}.csv"
        output_path = temp_path / f"output_{request.execution_id}.json"

        with open(script_path, "w") as f:
            f.write(request.code)

        try:
            env_type = os.environ.get("ENVIRONMENT", "local").lower()
            if env_type == "local":
                local_path = Path(request.dataset_uri)
                if not local_path.exists():
                    raise HTTPException(status_code=404, detail=f"Dataset not found: {local_path}")
                csv_source_path = str(local_path)
            else:
                if not BlobClient or not DefaultAzureCredential:
                    raise HTTPException(status_code=500, detail="Azure deps required for non-local env")
                storage_account_name = os.environ.get("STORAGE_ACCOUNT_NAME")
                if not storage_account_name:
                    raise ValueError("STORAGE_ACCOUNT_NAME is required")
                account_url = f"https://{storage_account_name}.blob.core.windows.net"
                parsed = urlparse(request.dataset_uri)
                if parsed.scheme and parsed.netloc:
                    path_parts = parsed.path.split("/")
                    container_name = path_parts[1]
                    blob_name = "/".join(path_parts[2:])
                else:
                    path = request.dataset_uri.lstrip("/")
                    parts = path.split("/")
                    if len(parts) < 2:
                        raise ValueError("dataset_uri must be '/<container>/<blob>'")
                    container_name = parts[0]
                    blob_name = "/".join(parts[1:])
                credential = DefaultAzureCredential()
                blob_client = BlobClient(
                    account_url=account_url,
                    container_name=container_name,
                    blob_name=blob_name,
                    credential=credential,
                )
                if not blob_client.exists():
                    raise HTTPException(status_code=404, detail=f"Dataset not found: {request.dataset_uri}")
                with open(data_path, "wb") as f:
                    f.write(blob_client.download_blob().readall())
                csv_source_path = str(data_path)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        runner_script = f"""
import json
import numpy as np
import pandas as pd
import math

input_df = pd.read_csv(r'{csv_source_path}')

SANDBOX_NAMESPACE = {{
    "pd": pd, "np": np, "numpy": np, "pandas": pd, "json": json, "math": math,
    "input_df": input_df.copy(deep=True), "output": None,
}}

def _sandbox_globals(): return SANDBOX_NAMESPACE
def _sandbox_locals(): return SANDBOX_NAMESPACE

SAFE_BUILTINS = {{
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len, "sorted": sorted,
    "enumerate": enumerate, "range": range, "round": round, "any": any, "all": all,
    "list": list, "dict": dict, "int": int, "float": float, "str": str, "bool": bool,
    "set": set, "tuple": tuple, "zip": zip, "map": map, "filter": filter,
    "reversed": reversed, "iter": iter, "next": next, "isinstance": isinstance,
    "issubclass": issubclass, "getattr": getattr, "hasattr": hasattr, "setattr": setattr,
    "delattr": delattr, "type": type, "callable": callable, "id": id, "hash": hash,
    "globals": _sandbox_globals, "locals": _sandbox_locals, "repr": repr,
    "chr": chr, "ord": ord, "format": format, "bin": bin, "print": print, "slice": slice,
}}

ALLOWED_MODULES = {{"numpy": np, "pandas": pd, "math": math, "json": json}}

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root in ALLOWED_MODULES:
        return ALLOWED_MODULES[root]
    raise ImportError("Imports disabled. Allowed: " + ", ".join(sorted(ALLOWED_MODULES.keys())))

SAFE_BUILTINS["__import__"] = _restricted_import
SANDBOX_NAMESPACE["__builtins__"] = SAFE_BUILTINS

def _stringify_output(value):
    if value is None: return "No output"
    if isinstance(value, pd.DataFrame): return value.to_csv(index=False)
    if isinstance(value, pd.Series): return value.to_csv(index=False)
    if isinstance(value, (list, tuple, set)): return json.dumps(list(value))
    if isinstance(value, (int, float, str)): return str(value)
    return repr(value)

try:
    with open(r'{script_path}', 'r') as f:
        code = f.read()
    exec(code, SANDBOX_NAMESPACE, SANDBOX_NAMESPACE)
    result = {{"success": True, "output": _stringify_output(SANDBOX_NAMESPACE.get("output"))}}
except Exception as e:
    result = {{"success": False, "code_execution_error": str(e)}}

with open(r'{output_path}', 'w') as f:
    json.dump(result, f)
"""
        runner_path = temp_path / "runner.py"
        with open(runner_path, "w") as f:
            f.write(runner_script)

        try:
            subprocess.run(
                [sys.executable, str(runner_path)],
                timeout=request.timeout_sec,
                check=True,
                capture_output=True,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail="Execution timed out")
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"Execution failed: {e.stderr.decode()}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        with open(output_path, "r") as f:
            return json.load(f)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
