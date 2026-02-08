from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import mujoco
from mujoco import viewer as mj_viewer

from app.runtime.bus import Bus


@dataclass
class MuJoCoSimReal:
    """
    Real MuJoCo simulator block.

    Ports
    -----
    input :  "command"  (type: cartesian_cmd)  expects {"dx": float}
    output:  "state"    (type: robot_state)

    Params
    ------
    model_path: str   (OPTIONAL with Option A) MJCF/XML path
      - "" or "mujoco://testdata/model.xml" => uses MuJoCo built-in test model
    dof_index: int    (default 0) which qpos index represents x
    dx_scale: float   (default 1.0) scale incoming dx
    apply_mode: str   (default "qpos") "qpos" | "qvel"
    substeps_per_tick: int (default 1)
    max_abs_x: float  (default 1e9) safety clamp
    """

    block_id: str
    params: Dict[str, Any]
    inputs: Dict[str, str]
    outputs: Dict[str, str]

    model: mujoco.MjModel = field(init=False)
    data: mujoco.MjData = field(init=False)

    _loaded: bool = field(default=False, init=False)
    _viewer: Optional[mj_viewer.Handle] = field(default=None, init=False)

    # --------------------------------------------------------------------- #
    # Utilities
    # --------------------------------------------------------------------- #

    def _resolve_model_path(self) -> Path:
        """
        Option A: if model_path is empty or is mujoco://testdata/model.xml,
        resolve to MuJoCo's bundled test model in a machine-independent way.
        """
        raw = str(self.params.get("model_path", "") or "").strip()

        # ✅ Option A defaults
        if raw == "" or raw.lower() == "mujoco://testdata/model.xml":
            mujoco_pkg_dir = Path(mujoco.__file__).resolve().parent
            return (mujoco_pkg_dir / "testdata" / "model.xml").resolve()

        # Normal paths
        return Path(raw).expanduser().resolve()

    # --------------------------------------------------------------------- #
    # Initialization
    # --------------------------------------------------------------------- #

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        model_path = self._resolve_model_path()
        if not model_path.exists():
            raise FileNotFoundError(f"{self.block_id}: model_path not found: {model_path}")

        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)

        # Optional reset to keyframe "home"
        try:
            kf = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "home")
            if kf != -1:
                mujoco.mj_resetDataKeyframe(self.model, self.data, kf)
        except Exception:
            pass

        mujoco.mj_forward(self.model, self.data)
        self._loaded = True

    # --------------------------------------------------------------------- #
    # Viewer
    # --------------------------------------------------------------------- #

    def maybe_open_viewer(self) -> None:
        """
        Open MuJoCo viewer once (passive mode).
        Safe to call before the first tick: it will load the model/data first.
        """
        self._ensure_loaded()

        if self._viewer is not None:
            return

        try:
            self._viewer = mj_viewer.launch_passive(self.model, self.data)
            print(f"[{self.block_id}] MuJoCo viewer opened")
        except Exception as e:
            print(f"[{self.block_id}] Viewer failed to open: {e}")
            self._viewer = None

    # --------------------------------------------------------------------- #
    # Runtime Tick
    # --------------------------------------------------------------------- #

    def tick(self, bus: Bus, t: int) -> None:
        self._ensure_loaded()

        cmd_topic = self.inputs.get("command")
        state_topic = self.outputs.get("state")
        if not state_topic:
            return

        # ------------------ Read command ------------------ #
        cmd = bus.read(cmd_topic) if cmd_topic else None
        dx = 0.0

        if cmd and cmd.type == "cartesian_cmd":
            try:
                dx = float(cmd.data.get("dx", 0.0))
            except Exception:
                dx = 0.0

        dx *= float(self.params.get("dx_scale", 1.0))

        dof_index = int(self.params.get("dof_index", 0))
        if self.model.nq > 0:
            dof_index = max(0, min(dof_index, self.model.nq - 1))
        else:
            dof_index = 0

        apply_mode = str(self.params.get("apply_mode", "qpos")).lower()
        max_abs_x = float(self.params.get("max_abs_x", 1e9))

        # ------------------ Apply command ------------------ #
        if self.model.nq > 0:
            if apply_mode == "qvel" and self.model.nv > 0:
                vidx = min(dof_index, self.model.nv - 1)
                self.data.qvel[vidx] += dx
            else:
                self.data.qpos[dof_index] += dx

            # Safety clamp
            if max_abs_x < 1e9:
                self.data.qpos[dof_index] = max(
                    -max_abs_x,
                    min(max_abs_x, self.data.qpos[dof_index]),
                )

        # ------------------ Step physics ------------------ #
        substeps = max(1, int(self.params.get("substeps_per_tick", 1)))
        for _ in range(substeps):
            mujoco.mj_step(self.model, self.data)

        # Sync viewer (if enabled)
        if self._viewer is not None:
            self._viewer.sync()
            time.sleep(0.0)  # let GUI breathe

        # ------------------ Publish state ------------------ #
        x = float(self.data.qpos[dof_index]) if self.model.nq > 0 else 0.0

        bus.publish(
            state_topic,
            "robot_state",
            {
                "x": x,
                "t": t,
                "time": float(self.data.time),
                "qpos0": float(self.data.qpos[0]) if self.model.nq > 0 else 0.0,
                "nq": int(self.model.nq),
                "nv": int(self.model.nv),
            },
            tick=t,
        )
