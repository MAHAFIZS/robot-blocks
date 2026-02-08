from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Protocol

from .bus import Bus


class Block(Protocol):
    block_id: str
    params: Dict[str, Any]

    def tick(self, bus: Bus, t: int) -> None:
        ...
