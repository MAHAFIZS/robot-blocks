import json
import yaml
from pathlib import Path

BLOCKS_DIR = Path(__file__).resolve().parents[2] / "blocks"
GRAPH_PATH = Path(__file__).resolve().parents[2] / "docs" / "graph_format.json"


def load_blocks():
    blocks = {}
    if not BLOCKS_DIR.exists():
        raise FileNotFoundError(f"Blocks dir not found: {BLOCKS_DIR}")

    for block_dir in BLOCKS_DIR.iterdir():
        block_file = block_dir / "block.yaml"
        if block_file.exists():
            with open(block_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                block = data["block"]
                blocks[block["name"]] = block
    return blocks


def load_graph():
    with open(GRAPH_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _ports_by_name(port_list):
    return {p["name"]: p for p in (port_list or [])}


def validate_graph(graph, blocks):
    # Build instance map: id -> block spec
    instances = {}
    for inst in graph.get("blocks", []):
        btype = inst["type"]
        if btype not in blocks:
            raise ValueError(f"Unknown block type: {btype}")
        instances[inst["id"]] = blocks[btype]

    # Validate connections
    connected_inputs = set()

    for c in graph.get("connections", []):
        # Parse "block.port"
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

    # Validate required inputs are connected
    for bid, spec in instances.items():
        for inp in spec.get("inputs", []) or []:
            if inp.get("required", False):
                key = (bid, inp["name"])
                if key not in connected_inputs:
                    raise ValueError(f"Missing required input: {bid}.{inp['name']}")

    return True



if __name__ == "__main__":
    blocks = load_blocks()
    graph = load_graph()

    validate_graph(graph, blocks)
    print("✅ Graph is valid")
    print("Loaded blocks:", list(blocks.keys()))
