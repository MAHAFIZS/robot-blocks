import json
from typing import Any

def _as_obj(x: Any) -> Any:
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x

class MuJoCoSim:
    def __init__(self, block_id, params, inputs, outputs):
        self.block_id = block_id
        self.params = params
        self.inputs = inputs
        self.outputs = outputs
        self.x = 0.0

    def tick(self, bus, t: int):
        cmd = bus.read(self.inputs["command"])

        if cmd and cmd.type == "cartesian_cmd":
            data = _as_obj(cmd.data)
            dx = float(data.get("dx", 0.0)) if isinstance(data, dict) else 0.0
        else:
            dx = 0.0

        dx_scale = float(self.params.get("dx_scale", 1.0))
        self.x += dx * dx_scale

        bus.publish(self.outputs["state"], "robot_state", {"x": self.x}, tick=t)
