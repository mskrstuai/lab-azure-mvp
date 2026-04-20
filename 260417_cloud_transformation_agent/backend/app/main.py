"""Cloud transformation agent backend — AWS scope → Azure migration plan."""

import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import aws_resources, migration

app = FastAPI(title="Cloud Transformation Agent API")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5174,http://localhost:5174")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(migration.router, prefix="/api")
app.include_router(aws_resources.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
