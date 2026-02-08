import json
import time
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
    runs = sorted(
        [p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")]
    )
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
    tick_period = 1.0 / max(hz, 1)

    viewer_enabled = bool(run_cfg.get("viewer", False))

    bus = Bus()

    resolved_by_id = {b["id"]: b for b in resolved}
    order = plan.get("execution_order", [b["id"] for b in resolved])
    connections = plan.get("connections", [])

    def port_topics(block_id: str, port_names: list[str]) -> dict[str, str]:
        # Convention: topic == "blockId.portName"
        return {p: f"{block_id}.{p}" for p in port_names}

    # -------------------- Instantiate blocks -------------------- #
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

    # -------------------- Viewer -------------------- #
    if viewer_enabled and "sim" in blocks:
        sim_blk = blocks["sim"]
        if hasattr(sim_blk, "maybe_open_viewer"):
            try:
                sim_blk.maybe_open_viewer()
            except Exception as e:
                print("[executor] Viewer requested but failed:", e)

    # -------------------- Routing -------------------- #
    def route_all(tick: int):
        for c in connections:
            src = c["from"]
            dst = c["to"]
            msg = bus.read(src)
            if msg:
                bus.publish(dst, msg.type, msg.data, tick=tick)

    # -------------------- Logging -------------------- #
    log_dir = run_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    state_log_path = log_dir / "state.jsonl"
    cmd_log_path = log_dir / "command.jsonl"

    state_log = open(state_log_path, "w", encoding="utf-8")
    cmd_log = open(cmd_log_path, "w", encoding="utf-8")

    # -------------------- Metrics -------------------- #
    last_x = 0.0
    max_x = -1e9

    print(f"▶ Running {ticks} ticks @ {hz} Hz (viewer={viewer_enabled})")

    try:
        for t in range(ticks):
            tick_start = time.perf_counter()

            # Route so blocks see latest inputs
            route_all(t)

            for bid in order:
                blocks[bid].tick(bus, t)
                route_all(t)

            # ---- Read messages ----
            st = bus.read("sim.state")
            cmd = bus.read("ctrl.command")

            # ---- Logging ----
            if st:
                state_log.write(
                    json.dumps(
                        {
                            "tick": t,
                            "msg_tick": st.tick,
                            "type": st.type,
                            "data": st.data,
                        }
                    )
                    + "\n"
                )

            if cmd:
                cmd_log.write(
                    json.dumps(
                        {
                            "tick": t,
                            "msg_tick": cmd.tick,
                            "type": cmd.type,
                            "data": cmd.data,
                        }
                    )
                    + "\n"
                )

            if (t % 20) == 0:
                state_log.flush()
                cmd_log.flush()

            # ---- Metrics ----
            if st and st.type == "robot_state":
                last_x = float(st.data.get("x", last_x))
                max_x = max(max_x, last_x)

            # ---- Real-time pacing ----
            elapsed = time.perf_counter() - tick_start
            remaining = tick_period - elapsed
            if remaining > 0:
                time.sleep(remaining)

    finally:
        state_log.flush()
        cmd_log.flush()
        state_log.close()
        cmd_log.close()

    metrics = {
        "duration_sec": duration,
        "hz": hz,
        "ticks": ticks,
        "final_x": last_x,
        "max_x": max_x,
        "goal_reached": last_x >= 0.5,
        "run_dir": str(run_dir),
        "viewer": viewer_enabled,
        "logs": {
            "state_jsonl": str(state_log_path),
            "command_jsonl": str(cmd_log_path),
        },
    }

    out_path = run_dir / "metrics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"✅ Run finished. Metrics written to: {out_path}")
    print(f"📝 Logs: {state_log_path} | {cmd_log_path}")

    # -------------------- Keep viewer alive -------------------- #
    if viewer_enabled and "sim" in blocks:
        sim_blk = blocks["sim"]
        if hasattr(sim_blk, "_viewer") and sim_blk._viewer is not None:
            print("🟦 MuJoCo viewer open. Close the window or press Ctrl+C to exit.")
            try:
                while True:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                print("🟨 Execution interrupted by user.")


if __name__ == "__main__":
    main()
