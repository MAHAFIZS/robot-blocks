from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.plan_graph import plan_graph_dict
from app.execute_run import execute_run_dir

app = FastAPI(title="robot-blocks API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/run")
def api_run(payload: Dict[str, Any]):
    graph = payload.get("graph")
    headless = bool(payload.get("headless", True))

    if not isinstance(graph, dict):
        raise HTTPException(status_code=400, detail="Missing 'graph' object in request body")

    try:
        run_dir = plan_graph_dict(graph)
        metrics = execute_run_dir(run_dir, viewer=(not headless))
        return {"run_dir": str(run_dir), "metrics": metrics}
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{e}\n\n{tb}")
