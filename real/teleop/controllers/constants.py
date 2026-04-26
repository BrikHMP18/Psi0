"""Constants for PICO controller-mode teleop.

All transformations not defined here are imported from the existing
hand-tracking pipeline (`constants_vuer`) to avoid duplication. The
controller-mode pipeline owns only the values that genuinely differ from
hand tracking: the controller-grip frame, locomotion deadzone/scale, and
crouch parameters.
"""

import numpy as np

# Re-exported from the existing pipeline. Downstream files in `controllers/`
# can `from controllers.constants import grd_yup2grd_zup, T_robot_openxr`
# without knowing the original location.
from constants_vuer import grd_yup2grd_zup, T_robot_openxr  # noqa: F401


# ---------------------------------------------------------------------------
# Frame transforms: PICO controller grip → Inspire / Unitree arm end-effector
# ---------------------------------------------------------------------------
#
# Initial best-guess: identical to `constants_vuer.hand2inspire_l_arm` and
# `hand2inspire_r_arm` because the OpenXR controller grip pose is
# approximately equivalent to the OpenXR hand wrist pose. Empirical
# calibration is expected during Fase 1 — adjust these matrices in place.
# Do NOT touch `constants_vuer.py`; that one still feeds hand-tracking mode.

CONTROLLER2INSPIRE_L_ARM = np.array([
    [1, 0,  0, 0],
    [0, 0, -1, 0],
    [0, 1,  0, 0],
    [0, 0,  0, 1],
], dtype=np.float64)

CONTROLLER2INSPIRE_R_ARM = np.array([
    [1,  0, 0, 0],
    [0,  0, 1, 0],
    [0, -1, 0, 0],
    [0,  0, 0, 1],
], dtype=np.float64)


# ---------------------------------------------------------------------------
# Locomotion mapping (used by `controllers/locomotion.py` in Fase 2)
# ---------------------------------------------------------------------------

STICK_DEADZONE = 0.15


# ---------------------------------------------------------------------------
# Crouch parameters (applied in `ControllerPreprocessor.process()` in Fase 3)
# ---------------------------------------------------------------------------
# `head_mat[2, 3] -= crouch_offset_z` — the IK in `solve_lower_ik` then
# lowers the torso automatically so the head reaches the new Z. Clamp keeps
# the offset within the AMO adapter's training distribution.

CROUCH_STEP_M = 0.005          # meters added/removed per 60 Hz frame
CROUCH_RANGE_M = (-0.20, 0.05)


# ---------------------------------------------------------------------------
# Dex3 hand qpos placeholders (Phase 4)
# ---------------------------------------------------------------------------
# Linear interpolation between OPEN and CLOSED based on the controller
# trigger value (0..1). The user's robot has no Dex3 physical hardware,
# so these are best-effort placeholders. The recorded episodes will be
# approximately compatible with a future Dex3 setup once the actual
# mechanical open/closed poses are calibrated.
#
# 7 floats per hand match the layout consumed by `Dex3_1_Controller` via
# `hand_shm_array[0:7]` (left) and `hand_shm_array[7:14]` (right) — see
# `master_whole_body.py:721-722`.
#
# TODO: replace with empirically-measured open/closed qpos vectors when
# Dex3 hardware arrives.

DEX3_OPEN_QPOS = np.zeros(7, dtype=np.float64)
DEX3_CLOSED_QPOS = np.array(
    [1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5], dtype=np.float64,
)


# ---------------------------------------------------------------------------
# Button → semantic action map
# ---------------------------------------------------------------------------
# E-STOP intentionally NOT mapped here. Identical to the original main.py
# flow: G1 gamepad button[3] (via DDS) and Ctrl+C on the laptop.

KEY_MAP = {
    "crouch_down":   "X",          # xrt.get_X_button() — left primary face button
    "stand_up":      "A",          # xrt.get_A_button() — right primary face button
    "gripper_left":  "trigger_l",  # xrt.get_left_trigger()  — 0..1 (Phase 4)
    "gripper_right": "trigger_r",  # xrt.get_right_trigger() — 0..1 (Phase 4)
}
