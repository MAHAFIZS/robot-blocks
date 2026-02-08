from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Message:
    type: str
    data: Any
    tick: int


class Bus:
    """
    Minimal in-memory pub/sub.
    - publish(topic, type, data, tick)
    - read(topic) -> latest Message or None
    """
    def __init__(self) -> None:
        self._topics: Dict[str, Message] = {}

    def publish(self, topic: str, msg_type: str, data: Any, tick: int) -> None:
        self._topics[topic] = Message(type=msg_type, data=data, tick=tick)

    def read(self, topic: str) -> Optional[Message]:
        return self._topics.get(topic)
