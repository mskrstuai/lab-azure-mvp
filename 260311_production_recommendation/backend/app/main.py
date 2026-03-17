"""Production Recommendation Backend - FastAPI app."""

import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import customers, inventory, model, chat

app = FastAPI(title="Production Recommendation API")

allowed_origins = os.getenv(
    "ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(model.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
