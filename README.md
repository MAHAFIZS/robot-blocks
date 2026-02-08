# Robot Blocks 🧱🤖

A **block-based robotics runtime** for building, executing, and reproducing robotics experiments without ROS launch-file chaos.

This project provides a clean, declarative alternative to traditional ROS/Gazebo workflows by introducing **blocks**, **explicit dataflow**, and **reproducible runs** — inspired by Simulink, LabVIEW, and AWS-style pipelines.

---

## 🚩 Motivation

Robotics experimentation often becomes messy:
- dozens of ROS nodes
- unclear topic wiring
- no reproducibility
- no clear notion of a “run”

**Robot Blocks** solves this by introducing:
- explicit block interfaces (inputs / outputs)
- validated execution graphs
- deterministic execution order
- per-run artifacts (logs, metrics, configs)

---

## 🧩 Core Concepts

### Blocks
Each block declares:
- inputs (ports)
- outputs (ports)
- parameters
- a runtime entrypoint

Example blocks:
- `CartesianControl`
- `MuJoCoSim` (real MuJoCo physics)
- (future) ROS2 bridge, perception, logging blocks

---

### Graph → Planner → Runtime

graph.json
↓
planner
↓
runs/run_000X/
├── plan.json
├── resolved_blocks.json
├── run_config.json
├── metrics.json
└── logs/


Each run is **fully reproducible**.

---

## 🎮 Features

- ✅ Block-based execution model
- ✅ Real MuJoCo simulation (headless or with viewer)
- ✅ `run_config.viewer` for reproducible visualization
- ✅ Real-time execution pacing
- ✅ Per-run logging (`state.jsonl`, `command.jsonl`)
- ✅ Metrics generation
- ✅ Deterministic execution order

---

## 🚀 Quick Start

### 1. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install mujoco