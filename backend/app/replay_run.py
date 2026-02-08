from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Repo layout:
# D:\Work\robot-blocks\
#   backend\app\replay_run.py   <-- this file
#   runs\run_000X\...
ROOT = Path(__file__).resolve().parents[1]        # ...\backend
PROJECT_ROOT = ROOT.parent                        # ...\robot-blocks
RUNS_DIR = PROJECT_ROOT / "runs"


def load_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip bad lines instead of failing the whole replay
                continue
    return rows


def list_runs() -> List[Path]:
    if not RUNS_DIR.exists():
        return []
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")]
    return sorted(runs)


def pick_run(run_name: Optional[str]) -> Path:
    runs = list_runs()
    if not runs:
        raise FileNotFoundError(f"No runs found in {RUNS_DIR}. Plan+execute at least one run first.")

    if run_name:
        candidate = RUNS_DIR / run_name
        if not candidate.exists():
            available = ", ".join([p.name for p in runs[-10:]])
            raise FileNotFoundError(f"Run not found: {candidate}. Available (last 10): {available}")
        return candidate

    # default: latest
    return runs[-1]


def extract_series(state_rows: List[Dict[str, Any]]) -> Tuple[List[int], List[float], List[float]]:
    """
    Returns (ticks, sim_time, x)
    """
    ticks: List[int] = []
    sim_time: List[float] = []
    x_series: List[float] = []

    for r in state_rows:
        t = r.get("tick", None)
        data = r.get("data", {}) or {}
        x = data.get("x", None)
        tm = data.get("time", None)

        if t is None or x is None:
            continue

        try:
            ticks.append(int(t))
            x_series.append(float(x))
            sim_time.append(float(tm) if tm is not None else float(t))
        except Exception:
            continue

    return ticks, sim_time, x_series


def summarize_run(run_dir: Path) -> Dict[str, Any]:
    metrics_path = run_dir / "metrics.json"
    run_cfg_path = run_dir / "run_config.json"

    metrics = load_json(metrics_path) if metrics_path.exists() else {}
    run_cfg = load_json(run_cfg_path) if run_cfg_path.exists() else {}

    state_path = run_dir / "logs" / "state.jsonl"
    cmd_path = run_dir / "logs" / "command.jsonl"

    state_rows = iter_jsonl(state_path)
    cmd_rows = iter_jsonl(cmd_path)

    ticks, sim_time, x_series = extract_series(state_rows)

    summary = {
        "run": run_dir.name,
        "paths": {
            "run_dir": str(run_dir),
            "metrics": str(metrics_path) if metrics_path.exists() else None,
            "run_config": str(run_cfg_path) if run_cfg_path.exists() else None,
            "state_log": str(state_path) if state_path.exists() else None,
            "command_log": str(cmd_path) if cmd_path.exists() else None,
        },
        "run_config": run_cfg,
        "metrics": metrics,
        "log_stats": {
            "state_rows": len(state_rows),
            "command_rows": len(cmd_rows),
            "parsed_state_points": len(x_series),
            "tick_min": min(ticks) if ticks else None,
            "tick_max": max(ticks) if ticks else None,
            "x_first": x_series[0] if x_series else None,
            "x_last": x_series[-1] if x_series else None,
            "x_min": min(x_series) if x_series else None,
            "x_max": max(x_series) if x_series else None,
        },
    }
    return summary


def try_plot(run_dir: Path, sim_time: List[float], x_series: List[float]) -> Optional[Path]:
    """
    Writes a PNG plot into the run directory if matplotlib is available.
    """
    if not x_series:
        return None

    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return None

    out_path = run_dir / "replay_x.png"

    plt.figure()
    plt.plot(sim_time, x_series)
    plt.title(f"{run_dir.name}: x over time")
    plt.xlabel("time (sim)")
    plt.ylabel("x")
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Replay/analyze a run from logs (no MuJoCo needed).")
    ap.add_argument("--run", type=str, default=None, help="Run folder name, e.g. run_0008. Default: latest.")
    ap.add_argument("--plot", action="store_true", help="Generate replay_x.png if matplotlib is available.")
    ap.add_argument("--write-summary", action="store_true", help="Write replay_summary.json into the run folder.")
    args = ap.parse_args()

    run_dir = pick_run(args.run)
    summary = summarize_run(run_dir)

    # Print summary nicely
    print("🟦 Replay summary")
    print(f"Run: {summary['run']}")
    print(f"State rows: {summary['log_stats']['state_rows']}, Commands: {summary['log_stats']['command_rows']}")
    print(f"Parsed points: {summary['log_stats']['parsed_state_points']}")
    print(f"x_first: {summary['log_stats']['x_first']}, x_last: {summary['log_stats']['x_last']}")
    print(f"x_min: {summary['log_stats']['x_min']}, x_max: {summary['log_stats']['x_max']}")

    # Optional plot
    if args.plot:
        state_rows = iter_jsonl(run_dir / "logs" / "state.jsonl")
        _, sim_time, x_series = extract_series(state_rows)
        plot_path = try_plot(run_dir, sim_time, x_series)
        if plot_path:
            print(f"📈 Plot written: {plot_path}")
        else:
            print("⚠️ Plot skipped (no data or matplotlib not installed).")

    # Optional write summary json
    if args.write_summary:
        out_path = run_dir / "replay_summary.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"📝 Summary written: {out_path}")


if __name__ == "__main__":
    main()
