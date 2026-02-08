from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
from .bus import Bus


@dataclass
class MuJoCoSimMock:
    block_id: str
    params: Dict[str, Any]
    in_command_topic: str
    out_state_topic: str

    # internal state
    x: float = 0.0

    def tick(self, bus: Bus, t: int) -> None:
        # Read latest command (if any)
        cmd = bus.read(self.in_command_topic)
        if cmd and cmd.type == "cartesian_cmd":
            dx = float(cmd.data.get("dx", 0.0))
        else:
            dx = 0.0

        # "simulate": x follows command
        self.x += dx

        # Publish robot_state
        bus.publish(
            self.out_state_topic,
            "robot_state",
            {"x": self.x, "t": t},
            tick=t,
        )
