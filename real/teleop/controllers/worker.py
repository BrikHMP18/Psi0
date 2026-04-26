"""Subprocess wrappers for controllers-mode data collection.

Phase 1: swaps the teleoperator class from `PicoTeleop`/`VuerTeleop` to
`ControllerTeleop`. Phase 2: also opens the controller_cmd_shm and writes
stick values to it on every step (consumed by `PicoStickShim` in master).
"""

import time
from multiprocessing import shared_memory

import numpy as np

from worker import RobotDataWorker, TeleoperatorProcess

from .pico_io import ControllerTeleop
from .locomotion import state_to_cmd_shm


class ControllerTeleoperatorProcess(TeleoperatorProcess):
    """`TeleoperatorProcess` using `ControllerTeleop` and writing the
    controller_cmd_shm.

    The parent's `__init__` instantiates `PicoTeleop()` unconditionally
    when `is_pico_streamer=True`, so we replicate the parent's body here
    instead and (a) swap the teleoperator instance, (b) open the cmd shm.
    """

    def __init__(
        self,
        teleop_shm_array,
        img_shm_name,
        kill_event,
        ir_data_queue,
        session_start_event,
        cmd_shm_name,
    ):
        # Replicates `TeleoperatorProcess.__init__` body (worker.py:167-185)
        # with the teleoperator type swapped and a connection to the
        # controller_cmd_shm added.
        self.teleop_shm_array = teleop_shm_array
        self.kill_event = kill_event
        self.ir_data_queue = ir_data_queue
        self.session_start_event = session_start_event
        self.is_pico_streamer = True

        self.img_shm = shared_memory.SharedMemory(name=img_shm_name)
        height, width = 720, 1280
        self.img_array = np.ndarray(
            (height, width, 3),
            dtype=np.uint8,
            buffer=self.img_shm.buf,
        )

        self.teleoperator = ControllerTeleop()

        # Phase 2: connect to the controller_cmd_shm created by the manager.
        self._cmd_shm = shared_memory.SharedMemory(name=cmd_shm_name)
        self._cmd_shm_array = np.ndarray(
            (8,), dtype=np.float64, buffer=self._cmd_shm.buf,
        )

        # Phase 3: give the preprocessor a view into the cmd_shm so it can
        # apply the head Z offset (crouch) inside `process()` each frame.
        self.teleoperator.processor.attach_cmd_shm(self._cmd_shm_array)

    def _step_loop(self):
        """Override of `TeleoperatorProcess._step_loop` (worker.py:206-224).

        Same body as the parent except for the cmd_shm write at the end of
        each iteration. The state we write was already read by
        `step()` → `processor.process()` so no extra xrt poll is needed.
        """
        prev_session_active = self.session_start_event.is_set()
        while not self.kill_event.is_set():
            curr_session_active = self.session_start_event.is_set()
            if curr_session_active and not prev_session_active:
                self.teleoperator.processor.trigger_calibration()
            prev_session_active = curr_session_active

            head_rmat, left_pose, right_pose, left_qpos, right_qpos = (
                self.teleoperator.step(full_head=True)
            )
            self.teleop_shm_array[0:16] = head_rmat.flatten()
            self.teleop_shm_array[16:32] = left_pose.flatten()
            self.teleop_shm_array[32:48] = right_pose.flatten()
            self.teleop_shm_array[48:55] = np.array(left_qpos).flatten()
            self.teleop_shm_array[55:62] = np.array(right_qpos).flatten()

            # Phase 2/3/4: pipe sticks/crouch/triggers into cmd_shm so
            # the master's PicoStickShim and ControllerPreprocessor see
            # them. During standby (no session active), zero the entire
            # cmd_shm so:
            #   - PICO sticks don't accidentally drive the robot via the
            #     AMO adapter while the operator is still settling into
            #     the headset (sticks live at cmd_shm[0:4]).
            #   - Crouch (cmd_shm[4]) and triggers (cmd_shm[5:7]) reset
            #     to zero so each new session starts neutral instead of
            #     inheriting state from the previous session.
            last_state = self.teleoperator.processor.last_state
            if last_state is not None and self.session_start_event.is_set():
                state_to_cmd_shm(last_state, self._cmd_shm_array)
            else:
                self._cmd_shm_array[:] = 0.0

            time.sleep(0.01)

    def run(self):
        """Inherits `TeleoperatorProcess.run()` and adds cmd_shm cleanup."""
        try:
            super().run()
        finally:
            try:
                self._cmd_shm.close()
            except Exception:
                pass


class ControllerDataWorker(RobotDataWorker):
    """`RobotDataWorker` that runs `ControllerTeleoperatorProcess` and
    forwards the cmd_shm name down to it.
    """

    def __init__(
        self,
        shared_data,
        robot_shm_array,
        teleop_shm_array,
        robot,
        is_pico_streamer,
        pico_ip,
        cmd_shm_name,
    ):
        # Must be set BEFORE super().__init__ because the parent forks the
        # teleop subprocess inside its constructor, and the bound method
        # `self._run_teleoperator_process` needs `self.cmd_shm_name`.
        self.cmd_shm_name = cmd_shm_name
        super().__init__(
            shared_data,
            robot_shm_array,
            teleop_shm_array,
            robot,
            is_pico_streamer,
            pico_ip,
        )

    def _run_teleoperator_process(
        self,
        teleop_shm_array,
        img_shm_name,
        kill_event,
        ir_data_queue,
        session_start_event,
    ):
        teleop_process = ControllerTeleoperatorProcess(
            teleop_shm_array,
            img_shm_name,
            kill_event,
            ir_data_queue,
            session_start_event,
            self.cmd_shm_name,
        )
        teleop_process.run()
