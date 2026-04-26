"""Entry point for PICO controllers-mode teleoperation + data collection.

Mirror of `main.py` for the controllers flow. Pick the entry script by
deciding which input modality you want to use:

    python main.py --robot g1 --pico_streamer --pico_ip <PICO_IP>
        # hand-tracking: the operator's bare hands drive the arms.

    python teleop_controllers.py --robot g1 --pico_ip <PICO_IP>
        # controllers: the PICO controllers drive the arms; sticks/buttons
        # drive locomotion + crouch (later phases). Two-person setup is
        # preserved (operator wears the headset, second person uses the
        # laptop REPL: `s` start, `q` save, `d` discard, `exit` quit).

Both scripts share the rest of the pipeline: shared memory, IK solver,
IKDataWriter, DataMerger, DDS, image server. Episode format is identical,
so datasets from the two modes can be merged and trained together.
"""

import argparse

from controllers.manager import ControllerTeleopManager


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Robot teleoperation + data collection (PICO controllers mode).",
    )
    parser.add_argument("--task_name", type=str, default="default_task",
                        help="Name of the task")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--robot", default="g1",
                        help="Use g1 controllers")
    parser.add_argument("--pico_ip", type=str, default="192.168.0.128",
                        help="PICO Wi-Fi IP for the IR streamer (camera→headset).")
    args = parser.parse_args()

    manager = ControllerTeleopManager(
        task_name=args.task_name,
        robot=args.robot,
        debug=args.debug,
        pico_ip=args.pico_ip,
    )
    manager.start_processes()
    manager.run_command_loop()
