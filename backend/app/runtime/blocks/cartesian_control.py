from __future__ import annotations

import json
from typing import Any, Dict


def _as_obj(x: Any) -> Any:
    """
    Normalize payloads:
    - If x is a JSON string like '{"x": 1}', decode to dict.
    - Otherwise return as-is.
    """
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


class CartesianControl:
    def __init__(self, block_id: str, params: Dict[str, Any], inputs: Dict[str, str], outputs: Dict[str, str]):
        self.block_id = block_id
        self.params = params or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}

    def tick(self, bus, t: int) -> None:
        # Read state message from bus
        state_topic = self.inputs.get("state")
        state = bus.read(state_topic) if state_topic else None

        # Extract x safely (supports dict payload or JSON-string payload)
        x = 0.0
        if state and getattr(state, "type", None) == "robot_state":
            data = _as_obj(getattr(state, "data", None))
            if isinstance(data, dict):
                try:
                    x = float(data.get("x", 0.0))
                except Exception:
                    x = 0.0

        goal_x = float(self.params.get("goal_x", 0.5))
        step = float(self.params.get("step", 0.005))

        dx = step if x < goal_x else 0.0

        # Publish command
        out_topic = self.outputs.get("command")
        if out_topic:
            bus.publish(out_topic, "cartesian_cmd", {"dx": dx}, tick=t)
