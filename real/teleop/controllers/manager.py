"""ControllerTeleopManager.

Phase 1: subclass of `TeleopManager` swapping the taskmaster + dataworker
process targets to controllers-mode subclasses.

Phase 2: also creates the `controller_cmd_shm` (8 float64s) and forwards
its name to both subprocesses so locomotion + (later) crouch + gripper
commands flow worker → master.
"""

from multiprocessing import Process, shared_memory

import numpy as np

from manager import TeleopManager

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

    def cleanup(self):
        super().cleanup()
        try:
            self._cmd_shm.close()
            self._cmd_shm.unlink()
        except Exception:
            pass
