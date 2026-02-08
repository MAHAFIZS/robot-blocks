# backend/app/plan_graph.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]       # .../backend
PROJECT_ROOT = ROOT.parent                       # repo root
RUNS_DIR = PROJECT_ROOT / "runs"
BLOCKS_DIR = PROJECT_ROOT / "blocks"


# -----------------------------------------------------------------------------
# Small utils
# -----------------------------------------------------------------------------
def load_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _next_run_dir(runs_dir: Path) -> Path:
    _ensure_dir(runs_dir)
    existing = sorted([d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run_")])
    if not existing:
        return runs_dir / "run_0001"
    last = existing[-1].name.replace("run_", "")
    try:
        n = int(last)
    except Exception:
        n = len(existing)
    return runs_dir / f"run_{n+1:04d}"


def _load_block_yaml(block_type: str) -> Dict[str, Any]:
    p = BLOCKS_DIR / block_type / "block.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Block type '{block_type}' not found. Missing: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
def _block_section(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Your block.yaml files are shaped like:
      block:
        inputs: ...
        outputs: ...
        params: ...
        runtime: ...
    So we must read from spec['block'].
    """
    b = spec.get("block")
    if isinstance(b, dict):
        return b
    return spec  # fallback if someone uses a flat YAML later


def _defaults_from_yaml(spec: Dict[str, Any]) -> Dict[str, Any]:
    b = _block_section(spec)
    defaults: Dict[str, Any] = {}
    for prm in (b.get("params") or []):
        name = prm.get("name")
        if name:
            defaults[name] = prm.get("default")
    return defaults


def _ports_from_yaml(spec: Dict[str, Any]) -> Dict[str, List[str]]:
    b = _block_section(spec)
    ins = [p.get("name") for p in (b.get("inputs") or []) if p.get("name")]
    outs = [p.get("name") for p in (b.get("outputs") or []) if p.get("name")]
    return {"inputs": ins, "outputs": outs}


def _normalize_entrypoint(ep: str) -> str:
    """
    You are running: python -m app.plan_graph / python -m app.execute_run
    So entrypoints must be importable as 'app....', not 'backend.app....'.

    If your block.yaml still contains backend.app..., normalize it automatically.
    """
    ep = (ep or "").strip()
    if ep.startswith("backend."):
        ep = ep[len("backend.") :]
    # also handle accidental 'backend/app/..' (rare)
    ep = ep.replace("backend.", "")
    return ep


def _runtime_from_yaml(spec: Dict[str, Any]) -> Dict[str, Any]:
    b = _block_section(spec)
    rt = b.get("runtime") or {}
    entrypoint = _normalize_entrypoint(rt.get("entrypoint", ""))
    return {
        "entrypoint": entrypoint,
        "supports_sim": bool(rt.get("supports_sim", True)),
    }


def _resolve_one_node(node: Dict[str, Any]) -> Dict[str, Any]:
    node_id = node["id"]
    block_type = node["type"]

    byaml = _load_block_yaml(block_type)
    defaults = _defaults_from_yaml(byaml)
    params_in = node.get("params") or {}
    merged_params = {**defaults, **params_in}

    runtime = _runtime_from_yaml(byaml)
    ports = _ports_from_yaml(byaml)

    if not runtime.get("entrypoint"):
        raise ValueError(f"blocks/{block_type}/block.yaml missing runtime.entrypoint")

    return {
        "id": node_id,
        "type": block_type,
        "runtime": runtime,
        "ports": ports,
        "params": merged_params,
    }


# -----------------------------------------------------------------------------
# Scheduling / planning
# -----------------------------------------------------------------------------
def _parse_endpoint(s: str) -> Tuple[str, str]:
    """
    "nodeId.portName" -> ("nodeId","portName")
    """
    if "." not in s:
        raise ValueError(f"Invalid endpoint '{s}'. Expected 'nodeId.port'")
    a, b = s.split(".", 1)
    return a, b


def _toposort(nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    """
    edges are (srcNodeId, dstNodeId) dependencies.
    """
    from collections import defaultdict, deque

    indeg = {n: 0 for n in nodes}
    adj = defaultdict(list)
    for u, v in edges:
        if u == v:
            continue
        if u not in indeg or v not in indeg:
            continue
        adj[u].append(v)
        indeg[v] += 1

    q = deque([n for n in nodes if indeg[n] == 0])
    out: List[str] = []

    while q:
        n = q.popleft()
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)

    if len(out) != len(nodes):
        raise ValueError("Cycle detected in graph dependencies")

    return out


def build_plan(graph: Dict[str, Any], resolved_blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Produces plan.json:
      - execution_order
      - connections: [{from,to}]
      - scheduling: meta
    """
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    node_ids = [n["id"] for n in nodes]

    # Use explicit order if present (best for cycle graphs like ctrl <-> sim)
    explicit = graph.get("execution_order")
    if explicit and isinstance(explicit, list) and len(explicit) > 0:
        for bid in explicit:
            if bid not in node_ids:
                raise ValueError(f"execution_order references unknown node id: {bid}")
        order = explicit
        scheduling = {"mode": "explicit"}
    else:
        # Try topo-sort based on edge direction (dst depends on src)
        # We interpret edges "from: A.out -> to: B.in" as B depends on A.
        deps: List[Tuple[str, str]] = []
        for e in edges:
            src = e.get("from")
            dst = e.get("to")
            if not src or not dst:
                continue
            src_node, _ = _parse_endpoint(src)
            dst_node, _ = _parse_endpoint(dst)
            deps.append((src_node, dst_node))

        try:
            order = _toposort(node_ids, deps)
            scheduling = {"mode": "toposort"}
        except ValueError:
            # fallback: stable node list order
            order = node_ids
            scheduling = {
                "mode": "fallback_node_list",
                "note": "Cycle detected; provide execution_order for deterministic scheduling.",
            }

    connections = []
    for e in edges:
        src = e.get("from")
        dst = e.get("to")
        if not src or not dst:
            continue
        connections.append({"from": src, "to": dst})

    return {
        "execution_order": order,
        "connections": connections,
        "scheduling": scheduling,
    }


# -----------------------------------------------------------------------------
# Main API used by http_server.py
# -----------------------------------------------------------------------------
def plan_graph_dict(graph: Dict[str, Any], runs_dir: Optional[Path] = None) -> Path:
    """
    Takes a graph.v1 dict and writes a runs/run_XXXX folder:
      - graph.v1.json
      - resolved_blocks.json
      - plan.json
      - run_config.json
      - logs/ (empty)
    Returns run_dir path.
    """
    if runs_dir is None:
        runs_dir = RUNS_DIR

    if graph.get("version") != "graph.v1":
        raise ValueError("Expected version='graph.v1'")

    nodes = graph.get("nodes") or []
    run_cfg = graph.get("run_config") or {}

    # Resolve blocks from blocks/<type>/block.yaml
    resolved_blocks = [_resolve_one_node(n) for n in nodes]

    # Build plan
    plan = build_plan(graph, resolved_blocks)

    # Normalize run config defaults
    run_cfg_out = {
        "duration_sec": int(run_cfg.get("duration_sec", 10)),
        "hz": int(run_cfg.get("hz", 20)),
        "viewer": bool(run_cfg.get("viewer", False)),
        "overrides": run_cfg.get("overrides") or {},
    }

    # Create run dir
    run_dir = _next_run_dir(runs_dir)
    _ensure_dir(run_dir)
    _ensure_dir(run_dir / "logs")

    write_json(run_dir / "graph.v1.json", graph)
    write_json(run_dir / "resolved_blocks.json", resolved_blocks)
    write_json(run_dir / "plan.json", plan)
    write_json(run_dir / "run_config.json", run_cfg_out)

    return run_dir


def plan_graph_file(graph_path: Path) -> Path:
    g = load_json(graph_path)
    return plan_graph_dict(g)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True, help="Path to graph.v1.json exported from frontend")
    args = ap.parse_args()

    graph_path = Path(args.graph).expanduser()
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph not found: {graph_path}")

    run_dir = plan_graph_file(graph_path)

    plan = load_json(run_dir / "plan.json")
    print(f"✅ Planned run: {run_dir}")
    print(f"Execution order: {plan.get('execution_order', [])}")
    print(f"Scheduling: {plan.get('scheduling', {})}")


if __name__ == "__main__":
    main()
