"""Cloud transformation agent backend — AWS scope → Azure migration plan."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

# Silence azure-identity's IMDS / ManagedIdentity probing noise.
# The DefaultAzureCredential chain tries IMDS first (always fails on a dev
# laptop) and the WARNINGs flood the log without being actionable.  Bumping
# the relevant loggers to ERROR keeps real auth failures visible.
for _noisy in ("azure.identity", "azure.core.pipeline.policies.http_logging_policy"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import architecture, aws_resources, credentials, deploy, migration, plan

app = FastAPI(title="Cloud Transformation Agent API")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5174,http://localhost:5174")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(credentials.router, prefix="/api")
app.include_router(architecture.router, prefix="/api")
app.include_router(plan.router, prefix="/api")
app.include_router(deploy.router, prefix="/api")
app.include_router(migration.router, prefix="/api")
app.include_router(aws_resources.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


from pathlib import Path as _Path
from fastapi import Body as _Body, HTTPException as _HTTPException

# Editable env keys exposed by the Settings UI.  Order is preserved on output.
_EDITABLE_KEYS = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]
_SECRET_KEYS = {"AZURE_OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}

# .env lives next to backend/app — i.e. <repo>/backend/.env
_ENV_FILE = _Path(__file__).resolve().parent.parent / ".env"


@app.get("/api/settings/env")
def settings_env_get():
    """Return current values for the editable settings keys.  Secrets are
    returned in full so the user can verify; the UI hides them behind a
    password input by default."""
    return {
        "keys":   _EDITABLE_KEYS,
        "values": {k: (os.getenv(k) or "") for k in _EDITABLE_KEYS},
        "secret_keys": sorted(_SECRET_KEYS),
        "env_file":    str(_ENV_FILE),
    }


def _write_env_updates(updates: dict) -> None:
    """Merge ``updates`` into the .env file in-place (preserving comments
    and unrelated keys), then update os.environ so the running server picks
    them up immediately."""
    lines: list[str] = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            new_lines.append(f"{key}={updates[key]}")
        else:
            new_lines.append(line)
    # Append keys that weren't already in the file
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")

    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ENV_FILE.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")

    # Reflect in current process so the next request sees new values
    for k, v in updates.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@app.post("/api/settings/env")
def settings_env_save(body: dict = _Body(...)):
    """Persist updated values for the editable settings keys.

    Body: ``{"values": {"AZURE_OPENAI_ENDPOINT": "...", ...}}``.

    Only keys in the editable allow-list are accepted.  Empty string clears
    a value (removed from os.environ; left empty in .env)."""
    in_values = (body or {}).get("values") or {}
    if not isinstance(in_values, dict):
        raise _HTTPException(status_code=400, detail="values must be a dict")
    updates = {}
    for k, v in in_values.items():
        if k not in _EDITABLE_KEYS:
            raise _HTTPException(status_code=400, detail=f"key not editable: {k}")
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise _HTTPException(status_code=400, detail=f"value for {k} must be string")
        updates[k] = v.strip()
    try:
        _write_env_updates(updates)
    except Exception as e:
        raise _HTTPException(status_code=500, detail=f".env 쓰기 실패: {e}")
    return {
        "saved":    sorted(updates.keys()),
        "values":   {k: (os.getenv(k) or "") for k in _EDITABLE_KEYS},
        "env_file": str(_ENV_FILE),
    }
