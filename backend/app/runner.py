import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]  # D:\Work\robot-blocks
BLOCKS_DIR = ROOT / "blocks"
DOCS_DIR = ROOT / "docs"
RUNS_DIR = ROOT / "runs"

GRAPH_PATH = DOCS_DIR / "graph_format.json"


def load_blocks():
    blocks = {}
    for block_dir in BLOCKS_DIR.iterdir():
        block_file = block_dir / "block.yaml"
        if block_file.exists():
            with open(block_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                b = data["block"]
                blocks[b["name"]] = b
    return blocks


def load_graph(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ports_by_name(port_list):
    return {p["name"]: p for p in (port_list or [])}


def validate_graph(graph, blocks):
    instances = {}
    for inst in graph.get("blocks", []):
        btype = inst["type"]
        if btype not in blocks:
            raise ValueError(f"Unknown block type: {btype}")
        instances[inst["id"]] = blocks[btype]

    connected_inputs = set()

    for c in graph.get("connections", []):
        def split_ref(ref: str):
            if "." not in ref:
                raise ValueError(f"Invalid ref '{ref}', expected 'blockId.portName'")
            bid, pname = ref.split(".", 1)
            return bid, pname

        from_bid, from_port = split_ref(c["from"])
        to_bid, to_port = split_ref(c["to"])

        if from_bid not in instances:
            raise ValueError(f"Unknown block id in 'from': {from_bid}")
        if to_bid not in instances:
            raise ValueError(f"Unknown block id in 'to': {to_bid}")

        from_spec = instances[from_bid]
        to_spec = instances[to_bid]

        from_outputs = _ports_by_name(from_spec.get("outputs"))
        to_inputs = _ports_by_name(to_spec.get("inputs"))

        if from_port not in from_outputs:
            raise ValueError(f"{from_bid} has no output port '{from_port}'")
        if to_port not in to_inputs:
            raise ValueError(f"{to_bid} has no input port '{to_port}'")

        out_type = from_outputs[from_port]["type"]
        in_type = to_inputs[to_port]["type"]

        if out_type != in_type:
            raise ValueError(
                f"Type mismatch: {c['from']} ({out_type}) -> {c['to']} ({in_type})"
            )

        connected_inputs.add((to_bid, to_port))

    for bid, spec in instances.items():
        for inp in spec.get("inputs", []) or []:
            if inp.get("required", False):
                if (bid, inp["name"]) not in connected_inputs:
                    raise ValueError(f"Missing required input: {bid}.{inp['name']}")

    return instances


def start_order_by_category(graph, instances):
    """
    Allow feedback loops. Compute a sensible startup order.
    Rule (MVP):
      sim -> perception -> decision -> control -> eval -> others
    """
    priority = {
        "sim": 10,
        "sensor": 20,
        "perception": 30,
        "decision": 40,
        "control": 50,
        "logging": 60,
        "eval": 70,
    }

    def prio(bid: str):
        cat = (instances[bid].get("category") or "other").lower()
        return priority.get(cat, 999), bid

    ids = [b["id"] for b in graph.get("blocks", [])]
    return [bid for bid in sorted(ids, key=prio)]



def next_run_dir():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not existing:
        return RUNS_DIR / "run_0001"
    last = existing[-1].name.split("_", 1)[1]
    n = int(last)
    return RUNS_DIR / f"run_{n+1:04d}"


def write_json(path: Path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def main():
    blocks = load_blocks()
    graph = load_graph(GRAPH_PATH)

    instances = validate_graph(graph, blocks)
    order = start_order_by_category(graph, instances)


    run_dir = next_run_dir()
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    # Build resolved block instances (with params, defaults)
    resolved = []
    for inst in graph["blocks"]:
        spec = instances[inst["id"]]
        params = {}
        for p in spec.get("params", []) or []:
            params[p["name"]] = p.get("default")
        # allow override in graph later (future)
        resolved.append({
    "id": inst["id"],
    "type": inst["type"],
    "params": params,
    "ports": {
        "inputs": [p["name"] for p in (spec.get("inputs") or [])],
        "outputs": [p["name"] for p in (spec.get("outputs") or [])],
    },
    "runtime": {
        "entrypoint": (spec.get("runtime") or {}).get("entrypoint", ""),
        "supports_sim": (spec.get("runtime") or {}).get("supports_sim", True),
    },
})


    plan = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "execution_order": order,
        "connections": graph.get("connections", []),
    }

    write_json(run_dir / "graph.json", graph)
    write_json(run_dir / "resolved_blocks.json", resolved)
    write_json(run_dir / "run_config.json", graph.get("run_config", {}))
    write_json(run_dir / "plan.json", plan)

    print(f"✅ Run planned: {run_dir}")
    print("Execution order:", order)


if __name__ == "__main__":
    main()
