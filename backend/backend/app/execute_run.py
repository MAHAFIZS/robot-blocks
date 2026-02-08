import json
from pathlib import Path

from app.runtime.bus import Bus
from app.runtime.loader import create_block

ROOT = Path(__file__).resolve().parents[1]   # backend/
PROJECT_ROOT = ROOT.parent                   # D:\Work\robot-blocks
RUNS_DIR = PROJECT_ROOT / "runs"


def load_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def latest_run_dir() -> Path:
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not runs:
        raise FileNotFoundError(f"No runs found in {RUNS_DIR}. Run planner first.")
    return runs[-1]


def main():
    run_dir = latest_run_dir()

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

    def port_topics(block_id: str, port_names: list[str]) -> dict[str, str]:
        # Convention: topic == "blockId.portName"
        return {p: f"{block_id}.{p}" for p in port_names}

    # Instantiate blocks dynamically
    blocks = {}
    for bid in order:
        spec = resolved_by_id[bid]
        entrypoint = (spec.get("runtime") or {}).get("entrypoint", "")
        if not entrypoint:
            raise ValueError(f"Missing runtime.entrypoint for block {bid}")

        in_ports = (spec.get("ports") or {}).get("inputs", [])
        out_ports = (spec.get("ports") or {}).get("outputs", [])

        blk = create_block(
            block_id=bid,
            params=spec.get("params", {}),
            entrypoint=entrypoint,
            inputs=port_topics(bid, in_ports),
            outputs=port_topics(bid, out_ports),
        )
        blocks[bid] = blk

    def route_all(tick: int):
        # Copy latest message from each connection source topic to destination topic
        for c in connections:
            src = c["from"]
            dst = c["to"]
            msg = bus.read(src)
            if msg:
                bus.publish(dst, msg.type, msg.data, tick=tick)

    # Metrics demo: track sim.state.x (works for your current pipeline)
    last_x = 0.0
    max_x = -1e9

    for t in range(ticks):
        # Route once so blocks see inputs before tick
        route_all(t)

        for bid in order:
            blocks[bid].tick(bus, t)
            # Route after each block tick so downstream sees fresh outputs
            route_all(t)

        st = bus.read("sim.state")
        if st and st.type == "robot_state":
            last_x = float(st.data.get("x", last_x))
            max_x = max(max_x, last_x)

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

    print(f"✅ Run executed. Metrics written to: {out_path}")
    print(metrics)


if __name__ == "__main__":
    main()
