"""Input mapping for PICO controllers.

Maps a `ControllerState` (raw xrt readings) into the values to write to
the `controller_cmd_shm`:

    [0]  lx                    Phase 2 — left stick X
    [1]  ly                    Phase 2 — left stick Y
    [2]  rx                    Phase 2 — right stick X
    [3]  ry                    Phase 2 — right stick Y
    [4]  head_z_offset         Phase 3 — meters added to head_mat[2,3]
                                          (signed; negative = crouch).
                                          Stateful: holding X decrements
                                          by `CROUCH_STEP_M` per frame,
                                          holding A increments. Clamped
                                          to `CROUCH_RANGE_M`.
    [5]  gripper_l             Phase 4 — 0..1 from left trigger
    [6]  gripper_r             Phase 4 — 0..1 from right trigger
    [7]  button_flags          Phase 3+ — bitmask (A,B,X,Y,menu_l,menu_r)

The shim in `controllers/master.py` reads [0:4] as lx/ly/rx/ry exactly as
if the values came from the G1 gamepad's wireless_remote DDS message.
This lets `master_whole_body.py:get_robot_data` apply its existing
`scale_vx/vy/vyaw` thresholds (0.3, 0.7, 0.2) unchanged — no need to
duplicate those closure-scoped functions here.

Crouch ([4]) is NOT consumed in master. It is read by
`ControllerPreprocessor.process()` in the worker subprocess and applied
directly to `head_mat[2,3]` before returning to `step()`. The IK in
`solve_lower_ik` then lowers the torso automatically so the head reaches
the new Z position.
"""

from __future__ import annotations

import numpy as np

from .constants import (
    CROUCH_RANGE_M,
    CROUCH_STEP_M,
    STICK_DEADZONE,
)
from .pico_io import ControllerState

CMD_SHM_SIZE = 8


def _apply_deadzone(v: float, deadzone: float = STICK_DEADZONE) -> float:
    """Snap |v| < deadzone to 0. A small noise floor on top of the per-axis
    thresholds applied later in `master_whole_body.py:scale_vx/vy/vyaw`.
    """
    return 0.0 if abs(v) < deadzone else v


def state_to_cmd_shm(state: ControllerState, out: np.ndarray) -> None:
    """Write the input mapping for `state` into `out` (length 8).

    Phase 2 (sticks):  [0:4] are written from `state.left_axis` / `right_axis`.
    Phase 3 (crouch):  [4] is read-modify-written based on X/A buttons.
    Phase 4 (gripper): [5], [6] will be written from triggers.
    """
    # --- Sticks (Phase 2) ---
    out[0] = _apply_deadzone(state.left_axis[0])   # lx
    out[1] = _apply_deadzone(state.left_axis[1])   # ly
    out[2] = _apply_deadzone(state.right_axis[0])  # rx
    out[3] = _apply_deadzone(state.right_axis[1])  # ry

    # --- Crouch (Phase 3) ---
    # Stateful read-modify-write. cmd_shm[4] is the cumulative head Z
    # offset in meters, applied as `head_mat[2,3] += offset` inside
    # `ControllerPreprocessor.process()`.
    head_z_offset = float(out[4])
    if state.button_x:
        head_z_offset -= CROUCH_STEP_M
    if state.button_a:
        head_z_offset += CROUCH_STEP_M
    lo, hi = CROUCH_RANGE_M
    out[4] = max(lo, min(hi, head_z_offset))

    # --- Gripper triggers (Phase 4) ---
    # Informational copy of the raw trigger values (0..1). The actual
    # Dex3 qpos vector that is fed to `Dex3_1_Controller` is computed
    # inside `ControllerPreprocessor.process()` via `_trigger_to_qpos`,
    # not consumed from here — these slots exist for visibility, future
    # logging, and potential debugging.
    out[5] = float(state.left_trigger)
    out[6] = float(state.right_trigger)
