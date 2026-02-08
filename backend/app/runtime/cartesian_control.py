from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
from .bus import Bus


@dataclass
class CartesianControlMock:
    block_id: str
    params: Dict[str, Any]
    in_state_topic: str
    out_command_topic: str

    def tick(self, bus: Bus, t: int) -> None:
        state = bus.read(self.in_state_topic)
        step = float(self.params.get("step_size", 0.01))

        # Simple policy: move +x until x >= 0.5, then stop
        x = float(state.data["x"]) if (state and state.type == "robot_state") else 0.0
        dx = step if x < 0.5 else 0.0

        bus.publish(
            self.out_command_topic,
            "cartesian_cmd",
            {"dx": dx},
            tick=t,
        )
