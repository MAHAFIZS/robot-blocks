from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _as_obj(x: Any) -> Any:
    """Decode JSON strings to objects; otherwise return unchanged."""
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


@dataclass
class Message:
    topic: str
    type: str
    data: Any
    tick: int = 0


class Bus:
    """
    In-process message bus.

    IMPORTANT:
    - Keep payloads as Python objects (dict/list/float).
    - Do NOT json.dumps() inside publish/read.
    - Only serialize when writing logs or sending API responses.
    """

    def __init__(self):
        self._store: Dict[str, Message] = {}

    def publish(self, topic: str, msg_type: str, data: Any, tick: int = 0) -> None:
        if not topic:
            return
        # Normalize if someone already serialized JSON
        data = _as_obj(data)
        self._store[topic] = Message(topic=topic, type=msg_type, data=data, tick=tick)

    def read(self, topic: Optional[str]) -> Optional[Message]:
        if not topic:
            return None
        msg = self._store.get(topic)
        if not msg:
            return None
        # extra safety normalization
        msg.data = _as_obj(msg.data)
        return msg
