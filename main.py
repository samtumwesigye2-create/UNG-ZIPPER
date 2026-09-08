"""UNG-ZIPPER entrypoint."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import threading

from zipper import router as zipper_router, bootstrap_from_ugamap, sync_state

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


@app.on_event("startup")
def bootstrap_registry():
    threading.Thread(target=bootstrap_from_ugamap, kwargs={"force": False}, daemon=True).start()


@app.get("/")
def root():
    state = sync_state()
    return {"service": "UNG-ZIPPER", "status": "ok" if state["records"] > 0 else "degraded", "records": state["records"]}


@app.get("/health")
def health():
    state = sync_state()
    return {"status": "ok", "records": state["records"], "sync_ok": state["ok"], "sync_attempted": state["attempted"]}


@app.get("/ready")
def ready():
    state = sync_state()
    if state["records"] <= 0:
        raise HTTPException(status_code=503, detail={"status": "not_ready", **state})
    return {"status": "ready", **state}
