"""ControllerTaskmaster + PicoStickShim.

Phase 2: install `PicoStickShim` over `body_ctrl.remote_controller` so the
master's existing `master_whole_body.py:get_robot_data` reads stick values
from the controller_cmd_shm transparently. Buttons (E-STOP via gamepad
button[3]) keep flowing through the original `RemoteController` because
the shim's `set()` proxies the DDS update unchanged and `.button` returns
the original's bit array.

Phase 3: nothing changes here — crouch is implemented in
`ControllerPreprocessor.process()` (lowers `head_mat[2, 3]` so
`solve_lower_ik` brings the torso down on its own).
"""

from __future__ import annotations

from multiprocessing import shared_memory

import numpy as np

from master_whole_body import RobotTaskmaster


class PicoStickShim:
    """Drop-in replacement for the `RemoteController` instance held at
    `body_ctrl.remote_controller`.

    - `.lx` / `.ly` / `.rx` / `.ry` read from the controller_cmd_shm.
    - `.button` proxies to the wrapped `RemoteController` so DDS-published
      button states (including `button[3]` = gamepad E-STOP) keep flowing.
    - `.set(data)` proxies to the wrapped `RemoteController` so the DDS
      subscriber thread in `BaseBodyController._subscribe_motor_state`
      keeps updating the original's button bits unchanged. The stick
      fields the original `set()` writes are simply ignored downstream
      because we read sticks from the shm.

    Properties (not cached attrs) so `master_whole_body.py:get_robot_data`
    reads up-to-date shm values on every frame.
    """

    def __init__(self, original, cmd_shm_array: np.ndarray) -> None:
        self._original = original
        self._shm = cmd_shm_array

    @property
    def lx(self) -> float:
        return float(self._shm[0])

    @property
    def ly(self) -> float:
        return float(self._shm[1])

    @property
    def rx(self) -> float:
        return float(self._shm[2])

    @property
    def ry(self) -> float:
        return float(self._shm[3])

    @property
    def button(self):
        return self._original.button

    def set(self, data) -> None:
        self._original.set(data)


class ControllerTaskmaster(RobotTaskmaster):
    """`RobotTaskmaster` with a `PicoStickShim` installed.

    Auto-stand-to-zero is preserved automatically because we inherit
    `start()` (which spawns the `maintain_standing` thread before blocking
    on `session_start_event.wait()`). Crouch logic is NOT here — it lives
    in `ControllerPreprocessor.process()` via head Z offset.
    """

    def __init__(
        self,
        task_name,
        shared_data,
        robot_shm_array,
        teleop_shm_array,
        robot,
        cmd_shm_name,
    ):
        super().__init__(
            task_name, shared_data, robot_shm_array, teleop_shm_array, robot,
        )

        self._cmd_shm = shared_memory.SharedMemory(name=cmd_shm_name)
        self._cmd_array = np.ndarray(
            (8,), dtype=np.float64, buffer=self._cmd_shm.buf,
        )

        # Swap the body controller's RemoteController for our shim. After
        # this, `master_whole_body.py:414` (`self.body_ctrl.remote_controller`)
        # transparently returns the shim — `lx/ly/rx/ry` come from the
        # cmd_shm; `button` comes from the original (DDS-fed, gamepad
        # E-STOP intact); `set()` calls keep flowing to the original from
        # the DDS subscriber thread.
        original_remote = self.body_ctrl.remote_controller
        self.body_ctrl.remote_controller = PicoStickShim(
            original_remote, self._cmd_array,
        )

    def stop(self) -> None:
        super().stop()
        try:
            self._cmd_shm.close()
        except Exception:
            pass
