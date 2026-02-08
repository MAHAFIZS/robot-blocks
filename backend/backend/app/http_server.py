from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Repo layout:
# repo_root/
#   backend/app/...
#   runs/run_XXXX/...
REPO_ROOT = Path(__file__).resolve().parents[2]   # .../robot-blocks
RUNS_DIR = REPO_ROOT / "runs"

app = FastAPI(title="robot-blocks API", version="0.1")

# Allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _latest_run_dir() -> Optional[Path]:
    if not RUNS_DIR.exists():
        return None
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    return runs[-1] if runs else None

def _run_cmd(args: list[str]) -> str:
    # Uses the SAME python interpreter running this server (your venv).
    cp = subprocess.run(
        [sys.executable] + args,
        cwd=str(REPO_ROOT / "backend"),
        capture_output=True,
        text=True,
    )
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    if cp.returncode != 0:
        raise RuntimeError(out.strip())
    return out.strip()

@app.get("/api/health")
def health():
    return {"ok": True, "repo_root": str(REPO_ROOT), "runs_dir": str(RUNS_DIR)}

@app.post("/api/run")
def run_graph(
    graph: Dict[str, Any] = Body(...),
    headless: bool = True,                 # default: don't open viewer from API
    run_dir: Optional[str] = None,         # optional: run an existing run folder
):
    """
    If run_dir is provided: execute it.
    Else: save graph to a temp file, plan it, then execute latest run.
    """
    try:
        if run_dir:
            rd = Path(run_dir)
            if not rd.exists():
                raise HTTPException(status_code=404, detail=f"run_dir not found: {run_dir}")
        else:
            # Save uploaded graph to a temp location
            tmp_dir = REPO_ROOT / "frontend" / "docs"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = tmp_dir / f"graph.upload.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            tmp_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")

            # Plan
            before = _latest_run_dir()
            _run_cmd(["-m", "app.plan_graph", "--graph", str(tmp_path)])
            after = _latest_run_dir()
            if not after or after == before:
                raise RuntimeError("Planner did not create a new run directory.")
            rd = after

        # Execute (headless by default)
        exec_args = ["-m", "app.execute_run", "--run", str(rd)]
        if headless:
            exec_args += ["--headless"]
        _run_cmd(exec_args)

        # Read metrics
        metrics_path = rd / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}

        return {
            "ok": True,
            "run_dir": str(rd),
            "metrics": metrics,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
