import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI

# Load .env from agents folder (required for Azure AI Search, OpenAI, etc.)
_env_path = Path(__file__).resolve().parent / "agents" / ".env"
load_dotenv(dotenv_path=_env_path)

# Configure logging (semantic_kernel, app)
_log_level = os.getenv("LOG_LEVEL", "INFO")
_level = getattr(logging, _log_level.upper(), logging.INFO)
logging.basicConfig(level=_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

_sk_log_level = os.getenv("SK_LOG_LEVEL", "DEBUG")
_sk_level = getattr(logging, _sk_log_level.upper(), logging.DEBUG)
logging.getLogger("semantic_kernel").setLevel(_sk_level)
logging.getLogger("azure").setLevel(logging.WARNING)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .database import Base, engine
from .routers import articles, chats, customers, preferences, transactions

Base.metadata.create_all(bind=engine)


def ensure_transactions_id_column():
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("transactions")}
    if "id" in columns:
        return

    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN id INTEGER"))
        except OperationalError as exc:
            if "duplicate column name: id" not in str(exc).lower():
                raise

    columns_after = {column["name"] for column in inspect(engine).get_columns("transactions")}
    if "id" in columns_after:
        with engine.begin() as conn:
            conn.execute(text("UPDATE transactions SET id = rowid WHERE id IS NULL"))


ensure_transactions_id_column()

app = FastAPI(title="H&M Personalized Recommendation Demo")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
image_dir = Path(__file__).resolve().parent.parent / "data" / "images"
image_dir.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(chats.router, prefix="/api")

app.mount("/images", StaticFiles(directory=str(image_dir)), name="images")


@app.get("/health")
def health():
    return {"status": "ok"}
