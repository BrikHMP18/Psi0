"""PICO controller I/O for teleop in controller mode.

Three classes, one role each:
- `ControllerReceiver`     — raw read of xrt state (Phase 0).
- `ControllerPreprocessor` — frame conversion, calibration, head→arm
                              transforms (Phase 1). Caches `last_state`
                              so the worker process can read sticks /
                              buttons without a second xrt poll (Phase 2).
                              Reads cmd_shm[4] and applies it as a Z
                              offset to head_mat for crouch (Phase 3).
- `ControllerTeleop`       — drop-in replacement for `vr_pico.PicoTeleop`
                              that the worker process spins up (Phase 1).

Phase 4 will extend `ControllerPreprocessor.process()` to derive
`left_q_target` / `right_q_target` from the controller triggers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import xrobotoolkit_sdk as xrt

# Reuse helpers from the hand-tracking pipeline — never duplicate.
from vr_pico import pose7_to_mat44, VuerPreprocessor, PicoTeleop
from motion_utils import fast_mat_inv, mat_update

# Sibling modules within the `controllers/` package.
from .constants import (
    CONTROLLER2INSPIRE_L_ARM,
    CONTROLLER2INSPIRE_R_ARM,
    DEX3_CLOSED_QPOS,
    DEX3_OPEN_QPOS,
    grd_yup2grd_zup,
)


def _trigger_to_qpos(trigger: float) -> np.ndarray:
    """Linear interpolation: trigger=0 → DEX3_OPEN_QPOS,
    trigger=1 → DEX3_CLOSED_QPOS. Clamps trigger to [0, 1].

    Returns a fresh `np.ndarray` of shape (7,) so callers can mutate it
    without affecting the constants.
    """
    t = max(0.0, min(1.0, float(trigger)))
    return (1.0 - t) * DEX3_OPEN_QPOS + t * DEX3_CLOSED_QPOS


# `|offset|` above this is treated as a misconfigured calibration (e.g.
# operator pulsed `s`/`t` while the headset was on a desk or in their
# lap). Empirically a normal standing/sitting calibration produces an
# offset in [0.0, 0.30] m.
_CALIBRATION_OFFSET_THRESHOLD_M = 0.40


def _format_calibration_banner(head_y: float, offset: float) -> str:
    """Return a multi-line banner describing the calibration result with
    a ✅/⚠️ badge based on `_CALIBRATION_OFFSET_THRESHOLD_M`.
    """
    if abs(offset) <= _CALIBRATION_OFFSET_THRESHOLD_M:
        badge = "  ✅ OK"
        tip = None
    else:
        badge = "  ⚠️  WARNING: offset alto."
        tip = (
            "      El headset estaba en una posición rara al calibrar.\n"
            "      Pulsá `q` para volver a standby, ponete bien el\n"
            "      headset, y volvé a pulsar `s` (o `t`) para recalibrar."
        )
    bar = "=" * 60
    lines = [
        bar,
        "  HEIGHT CALIBRATION",
        f"  Head Y (raw):  {head_y:+.3f} m",
        f"  Offset:        {offset:+.3f} m",
        badge,
    ]
    if tip is not None:
        lines.append(tip)
    lines.append(bar)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Receiver
# ---------------------------------------------------------------------------


@dataclass
class ControllerState:
    """Single snapshot of the PICO state read via xrt.

    `head_mat`, `left_mat`, `right_mat` are 4x4 numpy arrays in the OpenXR
    Y-up frame (raw from the SDK; frame conversion happens later in
    `ControllerPreprocessor`). Stick axes are (x, y) in [-1, 1]. Triggers
    and grips are scalars in [0, 1]. Buttons are booleans.
    """

    head_mat: np.ndarray
    left_mat: np.ndarray
    right_mat: np.ndarray

    left_axis: tuple[float, float]
    right_axis: tuple[float, float]

    left_trigger: float
    right_trigger: float
    left_grip: float
    right_grip: float

    button_a: bool
    button_b: bool
    button_x: bool
    button_y: bool
    menu_l: bool
    menu_r: bool
    axis_click_l: bool
    axis_click_r: bool


class ControllerReceiver:
    """Reads head + dual-controller pose, sticks, triggers, and buttons.

    Mirrors `vr_pico.PicoReceiver` but for the 2 physical controllers
    instead of hand tracking. Drop-in source for `ControllerPreprocessor`.
    """

    def __init__(self) -> None:
        try:
            print("[ControllerReceiver] Initializing PICO SDK...")
            xrt.init()
            print("[ControllerReceiver] PICO SDK initialized.")
        except Exception as exc:
            # Tolerated: SDK already initialized by another consumer in the
            # same process. Same pattern as `PicoReceiver` in vr_pico.py.
            print(f"[ControllerReceiver] xrt.init() raised: {exc}. Continuing.")

    def get_state(self) -> ControllerState:
        head_mat = pose7_to_mat44(xrt.get_headset_pose())
        left_mat = pose7_to_mat44(xrt.get_left_controller_pose())
        right_mat = pose7_to_mat44(xrt.get_right_controller_pose())

        l_axis = xrt.get_left_axis()
        r_axis = xrt.get_right_axis()

        return ControllerState(
            head_mat=head_mat,
            left_mat=left_mat,
            right_mat=right_mat,
            left_axis=(float(l_axis[0]), float(l_axis[1])),
            right_axis=(float(r_axis[0]), float(r_axis[1])),
            left_trigger=float(xrt.get_left_trigger()),
            right_trigger=float(xrt.get_right_trigger()),
            left_grip=float(xrt.get_left_grip()),
            right_grip=float(xrt.get_right_grip()),
            button_a=bool(xrt.get_A_button()),
            button_b=bool(xrt.get_B_button()),
            button_x=bool(xrt.get_X_button()),
            button_y=bool(xrt.get_Y_button()),
            menu_l=bool(xrt.get_left_menu_button()),
            menu_r=bool(xrt.get_right_menu_button()),
            axis_click_l=bool(xrt.get_left_axis_click()),
            axis_click_r=bool(xrt.get_right_axis_click()),
        )

    def stop(self) -> None:
        try:
            xrt.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------


# Index of the head Z offset in the controller_cmd_shm. Must match the
# layout documented in `controllers/locomotion.py`.
_CMD_SHM_HEAD_Z_OFFSET_IDX = 4


class ControllerPreprocessor(VuerPreprocessor):
    """Frame conversion + calibration for controller poses.

    Inherits from `VuerPreprocessor` so the calibration state
    (`y_offset`, `target_height`, `calibration_enabled`) and
    `trigger_calibration()` work identically. Only `process()` is
    overridden:
    - consumes a `ControllerState` instead of hand-tracking output;
    - applies `CONTROLLER2INSPIRE_*_ARM` instead of `hand2inspire_*_arm`;
    - returns zero-vectors for `left_q_target`/`right_q_target`
      (Phase 4 will derive these from the triggers).

    Phase 2: caches the most recent `ControllerState` in `self.last_state`
    so the worker process can read sticks/buttons without polling xrt
    a second time per frame.

    Phase 3: when a `cmd_shm_array` view is attached via
    `attach_cmd_shm()`, reads index 4 and applies it as a signed Z offset
    to `head_mat[2,3]` (in the robot Z-up frame) so `solve_lower_ik`
    lowers the torso for crouch.
    """

    def __init__(self, controller_receiver: ControllerReceiver):
        super().__init__(pico_receiver=None)
        self.controller_receiver = controller_receiver
        self.last_state: ControllerState | None = None
        self._cmd_shm_array: np.ndarray | None = None

    def attach_cmd_shm(self, cmd_shm_array: np.ndarray) -> None:
        """Give the preprocessor a view into `controller_cmd_shm`.

        Called by `ControllerTeleoperatorProcess.__init__` after opening
        the SHM. Once attached, `process()` reads the head Z offset from
        index 4 and applies it for crouch (Phase 3).
        """
        self._cmd_shm_array = cmd_shm_array

    def process(self):
        state = self.controller_receiver.get_state()
        self.last_state = state

        head_mat = mat_update(self.vuer_head_mat, state.head_mat)

        # Calibration: triggered once per session by `trigger_calibration()`
        # which the worker calls when the user presses `s` on the laptop.
        if (
            self.calibration_enabled
            and head_mat is not None
            and self.y_offset is None
        ):
            current_y = head_mat[1, 3]
            if not np.allclose(current_y, 0):
                self.y_offset = self.target_height - current_y
                print(_format_calibration_banner(current_y, self.y_offset))

        height_offset = self.y_offset if self.y_offset is not None else 0.0

        if head_mat is not None:
            head_mat[1, 3] += height_offset
        self.vuer_head_mat = head_mat

        if state.left_mat is not None:
            self.vuer_left_wrist_mat = mat_update(
                self.vuer_left_wrist_mat, state.left_mat,
            )
            self.vuer_left_wrist_mat[1, 3] += height_offset

        if state.right_mat is not None:
            self.vuer_right_wrist_mat = mat_update(
                self.vuer_right_wrist_mat, state.right_mat,
            )
            self.vuer_right_wrist_mat[1, 3] += height_offset

        # OpenXR Y-up → robot ground Z-up.
        head_mat = grd_yup2grd_zup @ self.vuer_head_mat @ fast_mat_inv(grd_yup2grd_zup)
        right_wrist_mat = (
            grd_yup2grd_zup @ self.vuer_right_wrist_mat @ fast_mat_inv(grd_yup2grd_zup)
        )
        left_wrist_mat = (
            grd_yup2grd_zup @ self.vuer_left_wrist_mat @ fast_mat_inv(grd_yup2grd_zup)
        )

        # Phase 3: crouch via head Z offset.
        # cmd_shm[4] is a signed offset in meters added to head_mat[2,3].
        # Negative (X button held) ⇒ head goes down ⇒ `solve_lower_ik`
        # lowers the torso so the head reaches that Z. Positive (A button
        # held) ⇒ head goes up. Wrist matrices are intentionally left
        # untouched: the IK targets stay where the controllers are
        # actually pointing in absolute world frame, so the user can
        # crouch with arms up (reach high while bent), with arms down
        # (reach low while bent), or anywhere in between.
        if self._cmd_shm_array is not None:
            head_mat[2, 3] += float(self._cmd_shm_array[_CMD_SHM_HEAD_Z_OFFSET_IDX])

        # Wrist matrices relative to head (with crouch already applied to
        # head). The CONTROLLER2INSPIRE_* matrices replace the hand-tracking
        # hand2inspire_* used in `VuerPreprocessor.process()` because the
        # PICO controller grip frame differs from the OpenXR hand wrist
        # frame. Calibrated empirically in Fase 1.
        rel_left_wrist_mat = (
            fast_mat_inv(head_mat) @ left_wrist_mat @ CONTROLLER2INSPIRE_L_ARM
        )
        rel_right_wrist_mat = (
            fast_mat_inv(head_mat) @ right_wrist_mat @ CONTROLLER2INSPIRE_R_ARM
        )

        # Phase 4: derive Dex3 finger qpos from the controller triggers.
        # The user's G1 has no Dex3 hardware so the values are not
        # physically actuated — but they ARE recorded by `IKDataWriter`
        # at `master_whole_body.py:726` (via `right_qpos`/`left_qpos`),
        # so the episodes stay approximately compatible with a future
        # Dex3 fine-tuning run. Open/closed reference poses come from
        # `controllers/constants.py` (placeholders, see TODO there).
        left_q_target = _trigger_to_qpos(state.left_trigger)
        right_q_target = _trigger_to_qpos(state.right_trigger)

        return (
            head_mat,
            rel_left_wrist_mat,
            rel_right_wrist_mat,
            left_q_target,
            right_q_target,
        )


# ---------------------------------------------------------------------------
# Teleop facade
# ---------------------------------------------------------------------------


class ControllerTeleop(PicoTeleop):
    """PICO controllers mirror of `PicoTeleop`.

    Inherits `step()` and `shutdown()` unchanged. Override `__init__` to
    wire `ControllerReceiver` + `ControllerPreprocessor` instead of the
    hand-tracking equivalents. The receiver is stored under the same
    attribute name (`pico_receiver`) so the inherited `shutdown()` keeps
    working without an override.
    """

    def __init__(self):
        # Do NOT call super().__init__() — it would create a hand-tracking
        # PicoReceiver. We attach our own components under the names the
        # parent's other methods expect.
        self.pico_receiver = ControllerReceiver()
        self.processor = ControllerPreprocessor(
            controller_receiver=self.pico_receiver,
        )
