from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# IMPORTANT:
# - plan_graph_dict() must exist in app.plan_graph.py (we already used it earlier)
# - execute_run_dir() must exist in app.execute_run.py (you have it now)
from app.plan_graph import plan_graph_dict
from app.execute_run import execute_run_dir

# For catalog scanning
try:
    import yaml  # pip install pyyaml
except Exception:
    yaml = None

APP_ROOT = Path(__file__).resolve().parents[0]          # backend/app
BACKEND_ROOT = APP_ROOT.parent                           # backend/
PROJECT_ROOT = BACKEND_ROOT.parent                       # repo root
BLOCKS_DIR = PROJECT_ROOT / "blocks"

app = FastAPI(title="robot-blocks-api")

# Allow frontend (vite) to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    graph: Dict[str, Any]
    headless: bool = True


@app.get("/health")
def health():
    return {"ok": True}


def _read_block_yaml(block_type: str) -> Dict[str, Any]:
    """
    Reads repo_root/blocks/<block_type>/block.yaml
    """
    p = BLOCKS_DIR / block_type / "block.yaml"
    if not p.exists():
        raise FileNotFoundError(f"blocks/{block_type}/block.yaml not found")

    if yaml is None:
        raise RuntimeError(
            "PyYAML not installed. Run: pip install pyyaml"
        )

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {p}")
    return data


def _discover_block_types() -> List[str]:
    if not BLOCKS_DIR.exists():
        return []
    out = []
    for d in sorted(BLOCKS_DIR.iterdir()):
        if d.is_dir() and (d / "block.yaml").exists():
            out.append(d.name)
    return out


@app.get("/api/catalog")
def api_catalog():
    """
    Returns catalog for frontend: list of blocks defined in /blocks/*/block.yaml
    """
    types = _discover_block_types()

    blocks = []
    for t in types:
        y = _read_block_yaml(t)

        # Expected YAML keys (keep tolerant):
        # label, category, ports: {inputs: [...], outputs: [...]}
        # params: {defaults: {...}}  (or "params_defaults")
        # runtime: {entrypoint: "..."}
        label = y.get("label", t)
        category = y.get("category", "other")

        ports = y.get("ports", {}) or {}
        inputs = ports.get("inputs", []) or []
        outputs = ports.get("outputs", []) or []

        # allow either params.defaults or params_defaults
        params_defaults = {}
        if isinstance(y.get("params"), dict) and isinstance(y["params"].get("defaults"), dict):
            params_defaults = y["params"]["defaults"]
        elif isinstance(y.get("params_defaults"), dict):
            params_defaults = y["params_defaults"]

        blocks.append(
            {
                "type": t,
                "label": label,
                "category": category,
                "inputs": inputs,
                "outputs": outputs,
                "params_defaults": params_defaults,
                "runtime": y.get("runtime", {}),
            }
        )

    return {"blocks": blocks}


@app.post("/api/run")
def api_run(req: RunRequest):
    """
    Frontend sends: { graph: <graph.v1>, headless: true/false }
    Backend:
      - plan graph into a new run_dir
      - execute run_dir
      - return metrics
    """
    graph = req.graph
    headless = bool(req.headless)

    try:
        run_dir = plan_graph_dict(graph)  # returns run_dir path (string or Path)
        metrics = execute_run_dir(run_dir, viewer=(not headless))
        return {"run_dir": str(run_dir), "metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
