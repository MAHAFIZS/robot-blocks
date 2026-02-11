from __future__ import annotations

import json
from typing import Any, Dict


def ensure_obj(x: Any) -> Any:
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


class MuJoCoSim:
    def __init__(self, block_id: str, params: Dict[str, Any], inputs: Dict[str, str], outputs: Dict[str, str]):
        self.block_id = block_id
        self.params = params or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.x = 0.0

    def tick(self, bus, t: int) -> None:
        cmd_topic = self.inputs.get("command")
        cmd = bus.read(cmd_topic) if cmd_topic else None

        dx = 0.0
        if cmd and getattr(cmd, "type", None) == "cartesian_cmd":
            data = ensure_obj(getattr(cmd, "data", None))
            if isinstance(data, dict):
                try:
                    dx = float(data.get("dx", 0.0))
                except Exception:
                    dx = 0.0

        dx *= float(self.params.get("dx_scale", 1.0))
        self.x += dx

        out_topic = self.outputs.get("state")
        if out_topic:
            bus.publish(out_topic, "robot_state", {"x": self.x, "t": t}, tick=t)
