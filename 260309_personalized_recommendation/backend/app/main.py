import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import articles, customers, transactions

Base.metadata.create_all(bind=engine)

app = FastAPI(title="H&M Personalized Recommendation Demo")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
image_dir = Path("./images")
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
app.include_router(transactions.router, prefix="/api")

app.mount("/images", StaticFiles(directory=str(image_dir)), name="images")


@app.get("/health")
def health():
    return {"status": "ok"}
