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
