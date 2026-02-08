from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict

from app.runtime.bus import Bus


@dataclass
class MuJoCoSimMock:
    block_id: str
    params: Dict[str, Any]
    inputs: Dict[str, str]   # port_name -> topic
    outputs: Dict[str, str]  # port_name -> topic

    x: float = 0.0

    def tick(self, bus: Bus, t: int) -> None:
        # Convention: sim has input port "command" and output port "state"
        cmd_topic = self.inputs.get("command")
        state_topic = self.outputs.get("state")

        cmd = bus.read(cmd_topic) if cmd_topic else None
        dx = float(cmd.data.get("dx", 0.0)) if (cmd and cmd.type == "cartesian_cmd") else 0.0

        self.x += dx

        if state_topic:
            bus.publish(
                state_topic,
                "robot_state",
                {"x": self.x, "t": t},
                tick=t,
            )
