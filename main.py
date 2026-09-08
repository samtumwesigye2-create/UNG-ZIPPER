"""UNG-ZIPPER entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from zipper import router as zipper_router

app = FastAPI(
    title="UNG-ZIPPER",
    description="National five-digit ZIP code registry - geographic source of truth",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(zipper_router)

@app.get("/")
def root():
    return {"service": "UNG-ZIPPER", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "ok"}
