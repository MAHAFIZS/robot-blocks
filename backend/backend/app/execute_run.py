"""
execute_run.py — Day 13-ready executor (dynamic blocks + routing + logging + MuJoCo viewer)

Run:
  # from D:\Work\robot-blocks\backend
  python -m app.execute_run
  python -m app.execute_run --run ..\runs\run_0013
  python -m app.execute_run --headless
  python -m app.execute_run --viewer
  python -m app.execute_run --hz 30 --duration 5

What it does:
- Loads latest (or specified) run directory created by plan_graph
- Instantiates blocks from resolved_blocks.json using runtime.entrypoint
- Routes messages according to plan.json connections (topic strings)
- Executes tick loop with optional real-time pacing
- Optional MuJoCo viewer open/hold behavior
- Writes metrics.json and also JSONL logs for state/command topics (if present)

Assumptions:
- Topic convention in planner: topics are "blockId.portName" (e.g., "sim.state", "ctrl.command")
- Your MuJoCoSimReal opens viewer based on run_config.viewer (or --viewer flag) and supports sim.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime.bus import Bus
from app.runtime.loader import create_block

# -----------------------------
# Paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]  # backend/
PROJECT_ROOT = ROOT.parent                 # repo root (D:\Work\robot-blocks)
RUNS_DIR = PROJECT_ROOT / "runs"


# -----------------------------
# Utils
# -----------------------------
def load_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def latest_run_dir() -> Path:
    if not RUNS_DIR.exists():
        raise FileNotFoundError(f"Runs folder not found: {RUNS_DIR}")
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not runs:
        raise FileNotFoundError(f"No runs found in {RUNS_DIR}. Run planner first.")
    return runs[-1]


def port_topics(block_id: str, port_names: List[str]) -> Dict[str, str]:
    # Convention: topic == "blockId.portName"
    return {p: f"{block_id}.{p}" for p in port_names}


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class JsonlLogger:
    """
    Minimal JSONL logger for selected topics.
    Writes rows like: {"t": 12, "topic": "sim.state", "type": "robot_state", "data": {...}}
    """
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.logs_dir = run_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._handles: Dict[str, Any] = {}

    def _file_for_topic(self, topic: str) -> Path:
        # e.g., "sim.state" -> "state.jsonl", "ctrl.command" -> "command.jsonl"
        # keep it simple but stable.
        safe = topic.replace("/", "_").replace(":", "_")
        return self.logs_dir / f"{safe.replace('.', '_')}.jsonl"

    def log_latest(self, bus: Bus, topic: str, t: int) -> None:
        msg = bus.read(topic)
        if not msg:
            return
        if topic not in self._handles:
            self._handles[topic] = open(self._file_for_topic(topic), "a", encoding="utf-8")

        row = {"t": t, "topic": topic, "type": msg.type, "data": msg.data}
        self._handles[topic].write(json.dumps(row) + "\n")
        self._handles[topic].flush()

    def close(self) -> None:
        for h in self._handles.values():
            try:
                h.close()
            except Exception:
                pass
        self._handles.clear()


# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=str, default="", help="Run directory (e.g., ..\\runs\\run_0013). Default: latest.")
    ap.add_argument("--hz", type=int, default=0, help="Override hz in run_config.json")
    ap.add_argument("--duration", type=int, default=0, help="Override duration_sec in run_config.json")
    ap.add_argument("--viewer", action="store_true", help="Force viewer on (if supported by sim block).")
    ap.add_argument("--headless", action="store_true", help="Force viewer off (no window).")
    ap.add_argument("--no_realtime", action="store_true", help="Disable real-time pacing.")
    ap.add_argument("--log_topics", type=str, default="", help="Comma-separated topics to log (default: auto).")
    args = ap.parse_args()

    # Resolve run dir
    run_dir = Path(args.run) if args.run else latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = (Path.cwd() / run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    plan = load_json(run_dir / "plan.json")
    resolved = load_json(run_dir / "resolved_blocks.json")
    run_cfg = load_json(run_dir / "run_config.json")

    # Apply overrides
    duration = int(args.duration or run_cfg.get("duration_sec", 10))
    hz = int(args.hz or run_cfg.get("hz", 20))
    ticks = duration * hz

    # Viewer toggle
    viewer_enabled = bool(run_cfg.get("viewer", False))
    if args.viewer:
        viewer_enabled = True
    if args.headless:
        viewer_enabled = False

    print(f"▶ Running {ticks} ticks @ {hz} Hz (viewer={viewer_enabled})")

    # Instantiate runtime
    bus = Bus()

    resolved_by_id = {b["id"]: b for b in resolved}
    order = plan.get("execution_order", [b["id"] for b in resolved])
    connections = plan.get("connections", [])

    # Instantiate blocks dynamically
    blocks: Dict[str, Any] = {}
    for bid in order:
        spec = resolved_by_id[bid]
        entrypoint = (spec.get("runtime") or {}).get("entrypoint", "")
        if not entrypoint:
            raise ValueError(f"Missing runtime.entrypoint for block {bid}")

        in_ports = (spec.get("ports") or {}).get("inputs", [])
        out_ports = (spec.get("ports") or {}).get("outputs", [])

        # Inputs/outputs dicts: portName -> topicName
        inputs = port_topics(bid, in_ports)
        outputs = port_topics(bid, out_ports)

        blk = create_block(
            block_id=bid,
            params={**spec.get("params", {}), "_viewer_enabled": viewer_enabled},  # optional hint
            entrypoint=entrypoint,
            inputs=inputs,
            outputs=outputs,
        )
        blocks[bid] = blk

    # Routing
    def route_all(tick: int):
        # Copy latest message from each connection source topic to destination topic
        for c in connections:
            src = c["from"]
            dst = c["to"]
            msg = bus.read(src)
            if msg:
                bus.publish(dst, msg.type, msg.data, tick=tick)

    # Logging: default log sim.state and ctrl.command if present
    if args.log_topics.strip():
        topics_to_log = [t.strip() for t in args.log_topics.split(",") if t.strip()]
    else:
        # auto-detect common topics by scanning ports
        topics_to_log = []
        for bid in order:
            spec = resolved_by_id[bid]
            outs = (spec.get("ports") or {}).get("outputs", [])
            for p in outs:
                topics_to_log.append(f"{bid}.{p}")

        # If you want only the interesting two:
        # topics_to_log = [t for t in topics_to_log if t.endswith(".state") or t.endswith(".command")]

    logger = JsonlLogger(run_dir)

    # Metrics demo: track first available *.state.x (robot_state)
    last_x = 0.0
    max_x = -1e9

    # Real-time pacing
    tick_dt = 1.0 / float(hz) if hz > 0 else 0.0

    try:
        for t in range(ticks):
            loop_start = time.time()

            # Route once so blocks see inputs before tick
            route_all(t)

            # Execute planned order (handles cycles via explicit scheduling)
            for bid in order:
                blocks[bid].tick(bus, t)
                route_all(t)

            # Log topics (latest values)
            for topic in topics_to_log:
                logger.log_latest(bus, topic, t)

            # Metrics: try to find any topic that ends with ".state"
            # Prefer "sim.state" if it exists, else take first available.
            st = bus.read("sim.state")
            if not st:
                # fallback: look for any state topic in log list
                state_topics = [tp for tp in topics_to_log if tp.endswith(".state")]
                if state_topics:
                    st = bus.read(state_topics[0])

            if st and st.type == "robot_state":
                last_x = safe_float(st.data.get("x", last_x), last_x)
                max_x = max(max_x, last_x)

            # Real-time pacing
            if not args.no_realtime and tick_dt > 0:
                elapsed = time.time() - loop_start
                sleep_time = tick_dt - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

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
        "run_dir": str(run_dir),
        "viewer": viewer_enabled,
        "logs_dir": str(run_dir / "logs"),
    }

    out_path = run_dir / "metrics.json"
    write_json(out_path, metrics)

    print(f"✅ Run finished. Metrics written to: {out_path}")

    # Optional: keep process alive so MuJoCo viewer stays open (if sim opened it)
    if viewer_enabled:
        print("🟦 MuJoCo viewer open. Close the window or press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("🟨 Viewer hold interrupted by user.")


if __name__ == "__main__":
    main()
