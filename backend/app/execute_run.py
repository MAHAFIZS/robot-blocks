import json
import time
from pathlib import Path
from typing import Dict, Any

from app.runtime.bus import Bus
from app.runtime.loader import create_block


ROOT = Path(__file__).resolve().parents[1]   # backend/
PROJECT_ROOT = ROOT.parent                   # repo root
RUNS_DIR = PROJECT_ROOT / "runs"


# -------------------------
# Helpers
# -------------------------

def load_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def latest_run_dir() -> Path:
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not runs:
        raise FileNotFoundError("No runs found. Plan a run first.")
    return runs[-1]


def port_topics(block_id: str, port_names: list[str]) -> dict[str, str]:
    # Convention: topic == "blockId.portName"
    return {p: f"{block_id}.{p}" for p in port_names}


# -------------------------
# CORE EXECUTOR (used by CLI + API)
# -------------------------

def execute_run_dir(run_dir: Path, viewer: bool = False) -> Dict[str, Any]:
    plan = load_json(run_dir / "plan.json")
    resolved = load_json(run_dir / "resolved_blocks.json")
    run_cfg = load_json(run_dir / "run_config.json")

    duration = int(run_cfg.get("duration_sec", 10))
    hz = int(run_cfg.get("hz", 20))
    ticks = duration * hz

    bus = Bus()

    resolved_by_id = {b["id"]: b for b in resolved}
    order = plan.get("execution_order", [b["id"] for b in resolved])
    connections = plan.get("connections", [])

    # -------------------------
    # Instantiate blocks
    # -------------------------
    blocks = {}

    for bid in order:
        spec = resolved_by_id[bid]

        runtime = spec.get("runtime") or {}
        entrypoint = runtime.get("entrypoint")
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

        # Optional viewer hook for sim blocks
        if viewer and hasattr(blk, "maybe_open_viewer"):
            blk.maybe_open_viewer()

        blocks[bid] = blk

    # -------------------------
    # Routing
    # -------------------------
    def route_all(tick: int):
        for c in connections:
            msg = bus.read(c["from"])
            if msg:
                bus.publish(c["to"], msg.type, msg.data, tick=tick)

    # -------------------------
    # Metrics
    # -------------------------
    last_x = 0.0
    max_x = -1e9

    # -------------------------
    # Main loop
    # -------------------------
    print(f"▶ Running {ticks} ticks @ {hz} Hz (viewer={viewer})")

    for t in range(ticks):
        route_all(t)

        for bid in order:
            blocks[bid].tick(bus, t)
            route_all(t)

        st = bus.read("sim.state")
        if st and st.type == "robot_state":
            last_x = float(st.data.get("x", last_x))
            max_x = max(max_x, last_x)

        # realtime pacing if viewer is on
        if viewer:
            time.sleep(1.0 / hz)

    metrics = {
        "duration_sec": duration,
        "hz": hz,
        "ticks": ticks,
        "final_x": last_x,
        "max_x": max_x,
        "goal_reached": last_x >= 0.5,
        "run_dir": str(run_dir),
    }

    out_path = run_dir / "metrics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"✅ Run finished. Metrics written to: {out_path}")
    return metrics


# -------------------------
# CLI entrypoint
# -------------------------

def main():
    run_dir = latest_run_dir()
    execute_run_dir(run_dir, viewer=False)


if __name__ == "__main__":
    main()
