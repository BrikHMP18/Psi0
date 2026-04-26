"""ControllerTeleopManager.

Phase 1: subclass of `TeleopManager` swapping the taskmaster + dataworker
process targets to controllers-mode subclasses.

Phase 2: also creates the `controller_cmd_shm` (8 float64s) and forwards
its name to both subprocesses so locomotion + (later) crouch + gripper
commands flow worker → master.
"""

import sys
from multiprocessing import Process, shared_memory

import numpy as np

from manager import TeleopManager
from teleop.utils.logger import logger

from .master import ControllerTaskmaster
from .worker import ControllerDataWorker


class ControllerTeleopManager(TeleopManager):
    """`TeleopManager` that wires the controllers-mode pipeline.

    `pico_streamer=True` is forced because controllers-mode also relies on
    `PicoIRStreamer` to push camera video to the headset (the operator
    wears the PICO and needs to see the robot's view).
    """

    def __init__(
        self,
        task_name="default_task",
        robot="g1",
        debug=False,
        pico_ip="192.168.0.128",
    ):
        super().__init__(
            task_name=task_name,
            robot=robot,
            debug=debug,
            pico_streamer=True,
            pico_ip=pico_ip,
        )

        # Phase 2: extra SHM for controller-specific commands. Layout
        # documented in `controllers/locomotion.py`.
        self._cmd_shm = shared_memory.SharedMemory(
            create=True,
            size=8 * np.dtype(np.float64).itemsize,
        )
        self._cmd_shm_array = np.ndarray(
            (8,), dtype=np.float64, buffer=self._cmd_shm.buf,
        )
        self._cmd_shm_array[:] = 0.0
        cmd_shm_name = self._cmd_shm.name

        # Signal the manager when the master is at standing pose and
        # ready to receive `s`/`t`. The manager's `run_command_loop`
        # blocks on this event so the `> ` REPL prompt only appears
        # after the master has printed the ROBOT READY banner.
        self.shared_dict["master_ready"] = self.manager.Event()

        # Replace the subprocess targets created by the parent. The
        # original Process objects were just configured (not yet started),
        # so swapping them in place before `start_processes()` is safe.
        def run_taskmaster():
            taskmaster = ControllerTaskmaster(
                self.task_name,
                self.shared_dict,
                self.robot_shm_array,
                self.teleop_shm_array,
                robot,
                cmd_shm_name,
            )
            taskmaster.start()

        def run_dataworker():
            taskworker = ControllerDataWorker(
                self.shared_dict,
                self.robot_shm_array,
                self.teleop_shm_array,
                robot,
                self.pico_streamer,
                self.pico_ip,
                cmd_shm_name,
            )
            taskworker.start()

        self.taskmaster_proc = Process(target=run_taskmaster)
        self.dataworker_proc = Process(target=run_dataworker)

    # ---- Teleop-only mode (Mejora 2) -----------------------------------

    def start_session(self, recording: bool = True):
        """Override: accept a `recording` flag.

        When `recording=False`, do NOT call `update_directory` (no
        episode folder is created) and set `shared_dict["recording_active"]`
        so `ControllerTaskmaster._session_init` knows to use a no-op
        writer. Default `True` keeps backward compatibility with any
        caller that uses the parent's no-arg form.
        """
        self.shared_dict["recording_active"] = recording
        if recording:
            self.update_directory()
        self.shared_dict["failure_event"].clear()
        self.shared_dict["kill_event"].clear()
        self.shared_dict["session_start_event"].set()
        if recording:
            logger.info("Recording session started.")
        else:
            logger.info("Teleop-only session started (no recording).")

    def run_command_loop(self):
        """Override of `TeleopManager.run_command_loop` adding the `t`
        (teleop-only) command and waiting for the master's "ready"
        signal so the `> ` REPL prompt only appears once the robot has
        reached standing pose and printed the ROBOT READY banner.

        Replicates the parent's body because the parent's REPL is a
        single while-loop with hard-coded `if user_input == "s"` etc.,
        so there's no clean hook to extend without duplicating.
        """
        logger.info(
            "Initializing robot (DDS, IK, motors)... "
            "wait for the ROBOT READY banner before typing."
        )
        if not self.shared_dict["master_ready"].wait(timeout=60):
            logger.warning(
                "Master ready signal not received within 60s. Continuing — "
                "you can type commands but the robot may not be ready yet."
            )

        last_cmd = None
        try:
            while True:
                user_input = input("> ").lower()
                if user_input == "s" and last_cmd != "s":
                    self.start_session(recording=True)
                    dirname = self.shared_dict["dirname"]
                    logger.info(f"Current task: {dirname}")
                    last_cmd = "s"
                elif user_input == "t" and last_cmd != "t":
                    self.start_session(recording=False)
                    last_cmd = "t"
                elif user_input == "q":
                    self.stop_session()
                    last_cmd = "q"
                elif user_input == "d":
                    self.shared_dict["failure_event"].set()
                    self.stop_session()
                    last_cmd = "d"
                elif user_input == "exit":
                    self.cleanup()
                    sys.exit(0)
                else:
                    logger.info(
                        "Invalid command. Use 's' record, 't' teleop-only, "
                        "'q' stop/merge, 'd' discard, 'exit' to quit."
                    )
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt detected. Exiting...")
            self.cleanup()
            sys.exit(0)

    def cleanup(self):
        # Defensive ordering: release MY shm BEFORE super().cleanup()
        # runs the subprocess joins. If a stray Ctrl+C interrupts the
        # parent inside `taskmaster_proc.join` / `dataworker_proc.join`,
        # the cmd_shm is already unlinked and won't show up in the
        # `resource_tracker: There appear to be N leaked shared_memory
        # objects` warning. Subprocesses keep their own mapping alive
        # until they exit, so any in-flight writes inside `_step_loop`
        # finish without error — `unlink()` only removes the *name*; the
        # OS frees the underlying buffer once everyone has `close()`d.
        try:
            self._cmd_shm.close()
            self._cmd_shm.unlink()
        except Exception:
            pass
        super().cleanup()
