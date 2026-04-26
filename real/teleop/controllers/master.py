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

import threading
from multiprocessing import shared_memory

import numpy as np

from master_whole_body import RobotTaskmaster
from teleop.utils.logger import logger

from .writers import NoOpIKDataWriter


def _print_master_ready_banner() -> None:
    """Multi-line banner printed by master each time it enters the
    "waiting for s/t" state.

    Visible to the operator at the moment the robot is actually standing
    and ready to receive commands — not 22 seconds earlier when the
    manager first started up and DDS was still subscribing.
    """
    bar = "=" * 60
    print(bar)
    print("  ROBOT READY — controllers mode")
    print()
    print("    t      teleop-only (validar sin grabar)")
    print("    s      start recording session")
    print("    q      stop current session (save if recording)")
    print("    d      stop and discard current session")
    print("    exit   shutdown")
    print()
    print("  E-STOP: button[3] del mando G1  ·  Ctrl+C laptop")
    print(bar, flush=True)


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

    def start(self):
        """Override of `RobotTaskmaster.start()`.

        Behavior identical to parent except:
        - prints `_print_master_ready_banner()` each time we (re)enter
          the wait-for-session state, so the operator sees the
          available commands at the moment the robot is actually
          standing (not 22 s earlier under DDS init logs);
        - signals `shared_data["master_ready"]` the FIRST time we hit
          the wait, so the manager process can hold its `> ` REPL
          prompt until then.

        The body is otherwise a verbatim copy of the parent's `start()`
        because the parent's loop has no clean hook to extend.
        """
        try:
            stabilize_thread = threading.Thread(
                target=self.maintain_standing, daemon=True,
            )
            self.reset_yaw_offset = True
            stabilize_thread.start()

            first_wait = True
            while not self.end_event.is_set():
                logger.info("Master: waiting to start")
                _print_master_ready_banner()
                if first_wait:
                    self.shared_data["master_ready"].set()
                    first_wait = False
                self.session_start_event.wait()
                logger.info(
                    "Master: start event recvd. clearing start event. starting session"
                )
                self.reset_yaw_offset = True
                self.run_session()
                logger.debug("Master: merging data...")
                if not self.failure_event.is_set():
                    self.merge_data()
                    logger.info("Master: merge finished. Preparing for a new run...")
                else:
                    logger.info(
                        "Master: not merging. Preparing for a new run to override..."
                    )
                self.reset()
                logger.info("Master: reset finished")
        finally:
            self.stop()
            if self.robot == "g1":
                self.hand_shm.close()
                self.hand_shm.unlink()
            logger.info("Master: exited")

    # ---- Teleop-only mode (Mejora 2) -----------------------------------
    #
    # The manager sets `shared_data["recording_active"]` based on whether
    # the user pressed `s` (recording=True) or `t` (recording=False).
    # When False, we use a `NoOpIKDataWriter` so `run_session` runs
    # full IK + motor commands but writes nothing to disk, and we
    # short-circuit `merge_data` so no folder is touched.

    def _session_init(self):
        """Override: pick the writer based on the session type.

        Recording session  → real `IKDataWriter` (parent behavior).
        Teleop-only session → `NoOpIKDataWriter` (writes are swallowed).

        Backward-compatible: if `recording_active` is missing from
        `shared_data` we default to recording (parent behavior).
        """
        recording = self.shared_data.get("recording_active", True)
        if recording:
            super()._session_init()
        else:
            self.running = True
            self.ik_writer = NoOpIKDataWriter()
            logger.info("Master: starting teleop-only session (no recording).")

    def merge_data(self):
        """Override: skip merging for teleop-only sessions.

        The NoOp writer has no JSON to merge and `shared_data["dirname"]`
        may not even be set. Just close the writer (also a no-op) and
        return.
        """
        recording = self.shared_data.get("recording_active", True)
        if not recording:
            if self.ik_writer is not None:
                self.ik_writer.close()
            return
        super().merge_data()

    def reset(self):
        """Override: skip the parent's eager `IKDataWriter(dirname)`
        re-creation. The next `_session_init()` will set the writer
        cleanly (real or no-op) before any frame runs, so re-creating
        it here would be both wasteful and unsafe in teleop-only mode
        where `dirname` may not be set.
        """
        if self.running:
            self.stop()
        self.hand_ctrl.reset()
        self.body_ctrl.reset()
        self.first = True
        self.running = False
        self.robot_shm_array[:] = 0
        # Intentionally NOT recreating self.ik_writer here.
        logger.info("RobotTaskmaster has been reset and is ready to start again.")
