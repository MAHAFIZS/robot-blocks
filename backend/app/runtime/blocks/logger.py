from __future__ import annotations

import json
from typing import Any, Dict


def _as_obj(x: Any) -> Any:
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


class Logger:
    def __init__(self, block_id: str, params: Dict[str, Any], inputs: Dict[str, str], outputs: Dict[str, str]):
        self.block_id = block_id
        self.params = params or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}

        self.tag = str(self.params.get("tag", "run"))
        self.every_n = int(self.params.get("every_n", 1))
        self.k = 0

    def tick(self, bus, t: int) -> None:
        self.k += 1
        if self.every_n > 1 and (self.k % self.every_n) != 0:
            return

        state_topic = self.inputs.get("state")
        msg = bus.read(state_topic) if state_topic else None
        if not msg:
            return

        # normalize payload; but logger does NOT call .get() unless it's a dict
        data = _as_obj(getattr(msg, "data", None))

        # simplest: publish nothing; you can later write to run_dir logs
        # (If you want logging here, keep it in memory or write file.)
        # For now: do nothing to avoid side effects.
        _ = {"t": t, "tag": self.tag, "type": getattr(msg, "type", None), "data": data}
