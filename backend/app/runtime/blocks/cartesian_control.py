from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict

from backend.app.runtime.bus import Bus



@dataclass
class CartesianControlMock:
    block_id: str
    params: Dict[str, Any]
    inputs: Dict[str, str]   # port_name -> topic
    outputs: Dict[str, str]  # port_name -> topic

    def tick(self, bus: Bus, t: int) -> None:
        # Convention: ctrl has input port "state" and output port "command"
        state_topic = self.inputs.get("state")
        cmd_topic = self.outputs.get("command")

        state = bus.read(state_topic) if state_topic else None
        step = float(self.params.get("step_size", 0.01))

        x = float(state.data.get("x", 0.0)) if (state and state.type == "robot_state") else 0.0
        dx = step if x < 0.5 else 0.0

        if cmd_topic:
            bus.publish(
                cmd_topic,
                "cartesian_cmd",
                {"dx": dx},
                tick=t,
            )
