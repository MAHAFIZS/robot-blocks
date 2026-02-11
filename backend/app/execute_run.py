"""
execute_run.py — Day 13/14-ready executor

Run examples (from backend/):
  python -m app.execute_run
  python -m app.execute_run --run ..\\runs\\run_0013
  python -m app.execute_run --headless
  python -m app.execute_run --viewer
  python -m app.execute_run --hz 30 --duration 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime.bus import Bus
from app.runtime.loader import create_block

# -------------------------------------------------
# Paths
# -------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]      # backend/
PROJECT_ROOT = ROOT.parent                      # repo root
RUNS_DIR = PROJECT_ROOT / "runs"


# -------------------------------------------------
# Utils
# -------------------------------------------------
def load_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def latest_run_dir() -> Path:
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not runs:
        raise FileNotFoundError("No runs found. Run plan_graph first.")
    return runs[-1]


def port_topics(block_id: str, ports: List[str]) -> Dict[str, str]:
    return {p: f"{block_id}.{p}" for p in ports}


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def ensure_obj(x: Any) -> Any:
    """Decode JSON strings back into Python objects."""
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


def find_primary_robot_state_topic(order: List[str], resolved_by_id: Dict[str, Any]) -> Optional[str]:
    """
    Prefer sim-category block's 'state' output if present.
    Otherwise first output port named 'state'.
    """
    for bid in order:
        spec = resolved_by_id.get(bid, {})
        cat = str(spec.get("category") or "").lower()
        outs = (spec.get("ports") or {}).get("outputs", []) or []
        if cat == "sim" and "state" in outs:
            return f"{bid}.state"

    for bid in order:
        spec = resolved_by_id.get(bid, {})
        outs = (spec.get("ports") or {}).get("outputs", []) or []
        if "state" in outs:
            return f"{bid}.state"

    return None


# -------------------------------------------------
# JSONL Logger
# -------------------------------------------------
class JsonlLogger:
    def __init__(self, run_dir: Path):
        self.dir = run_dir / "logs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.handles: Dict[str, Any] = {}

    def _path(self, topic: str) -> Path:
        return self.dir / f"{topic.replace('.', '_')}.jsonl"

    def log(self, bus: Bus, topic: str, t: int):
        msg = bus.read(topic)
        if not msg:
            return
        if topic not in self.handles:
            self.handles[topic] = open(self._path(topic), "a", encoding="utf-8")

        row = {"t": t, "topic": topic, "type": msg.type, "data": msg.data}
        self.handles[topic].write(json.dumps(row) + "\n")
        self.handles[topic].flush()

    def close(self):
        for h in self.handles.values():
            try:
                h.close()
            except Exception:
                pass


# -------------------------------------------------
# Core executor (shared by CLI + API)
# -------------------------------------------------
def execute_run_dir(run_dir: Path | str, viewer: bool = True) -> Dict[str, Any]:
    run_dir = Path(run_dir)

    plan = load_json(run_dir / "plan.json")
    resolved = load_json(run_dir / "resolved_blocks.json")
    run_cfg = load_json(run_dir / "run_config.json")

    run_cfg["viewer"] = bool(viewer)
    return _execute(plan, resolved, run_cfg, run_dir)


def _execute(plan, resolved, run_cfg, run_dir: Path) -> Dict[str, Any]:
    duration = int(run_cfg.get("duration_sec", 10))
    hz = int(run_cfg.get("hz", 20))
    ticks = duration * hz
    viewer_enabled = bool(run_cfg.get("viewer", False))

    print(f"▶ Running {ticks} ticks @ {hz} Hz (viewer={viewer_enabled})")

    bus = Bus()
    resolved_by_id: Dict[str, Any] = {b["id"]: b for b in resolved}
    order: List[str] = plan.get("execution_order", [b["id"] for b in resolved])
    connections = plan.get("connections", [])

    # Instantiate blocks
    blocks: Dict[str, Any] = {}
    for bid in order:
        spec = resolved_by_id[bid]
        rt = spec.get("runtime", {})
        entrypoint = rt.get("entrypoint")
        if not entrypoint:
            raise ValueError(f"Missing runtime.entrypoint for block {bid}")

        ports = spec.get("ports") or {}
        in_ports = ports.get("inputs", [])
        out_ports = ports.get("outputs", [])

        blk = create_block(
            block_id=bid,
            params=spec.get("params", {}),
            entrypoint=entrypoint,
            inputs=port_topics(bid, in_ports),
            outputs=port_topics(bid, out_ports),
        )

        if viewer_enabled and hasattr(blk, "maybe_open_viewer"):
            blk.maybe_open_viewer()

        blocks[bid] = blk

    # routing
    def route(tick: int):
        for c in connections:
            msg = bus.read(c["from"])
            if not msg:
                continue
            bus.publish(c["to"], msg.type, ensure_obj(msg.data), tick=tick)

    logger = JsonlLogger(run_dir)

    topics_to_log: List[str] = []
    for bid in order:
        for p in resolved_by_id[bid].get("ports", {}).get("outputs", []):
            topics_to_log.append(f"{bid}.{p}")

    state_topic = find_primary_robot_state_topic(order, resolved_by_id) or "sim.state"

    last_x = 0.0
    max_x = -1e9
    dt = 1.0 / hz if hz > 0 else 0.0

    try:
        for t in range(ticks):
            start = time.time()

            route(t)
            for bid in order:
                blocks[bid].tick(bus, t)
                route(t)

            for tp in topics_to_log:
                logger.log(bus, tp, t)

            st = bus.read(state_topic)
            if st and st.type == "robot_state":
                st_data = ensure_obj(st.data)
                if isinstance(st_data, dict):
                    last_x = safe_float(st_data.get("x", last_x), last_x)
                    max_x = max(max_x, last_x)

            if dt > 0:
                sleep = dt - (time.time() - start)
                if sleep > 0:
                    time.sleep(sleep)

    except KeyboardInterrupt:
        print("🟨 Execution interrupted by user.")
    finally:
        logger.close()

    metrics = {
        "duration_sec": duration,
        "hz": hz,
        "ticks": ticks,
        "final_x": last_x,
        "max_x": max_x,
        "goal_reached": last_x >= 0.5,
        "viewer": viewer_enabled,
        "run_dir": str(run_dir),
        "metrics_state_topic": state_topic,
    }

    write_json(run_dir / "metrics.json", metrics)
    return metrics


# -------------------------------------------------
# CLI entrypoint
# -------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=str, default="")
    ap.add_argument("--hz", type=int, default=0)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--viewer", action="store_true")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run) if args.run else latest_run_dir()
    run_dir = run_dir.resolve()

    run_cfg = load_json(run_dir / "run_config.json")
    if args.hz:
        run_cfg["hz"] = args.hz
    if args.duration:
        run_cfg["duration_sec"] = args.duration
    if args.viewer:
        run_cfg["viewer"] = True
    if args.headless:
        run_cfg["viewer"] = False

    write_json(run_dir / "run_config.json", run_cfg)
    metrics = execute_run_dir(run_dir, viewer=run_cfg.get("viewer", False))

    print(f"✅ Run finished. Metrics written to {run_dir / 'metrics.json'}")
    print(metrics)

    if run_cfg.get("viewer"):
        print("🟦 Viewer open. Close window or Ctrl+C to exit.")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
