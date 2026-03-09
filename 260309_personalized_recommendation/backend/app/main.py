from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import articles, customers, transactions

Base.metadata.create_all(bind=engine)

app = FastAPI(title="H&M Personalized Recommendation Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")

app.mount("/images", StaticFiles(directory="./images", check_dir=False), name="images")


@app.get("/health")
def health():
    return {"status": "ok"}
