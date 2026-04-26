#!/usr/bin/env python3
"""Probe the PICO controllers via XRoboToolkit before integrating.

Run from `real/teleop/` with the `psi_deploy` conda env active:

    cd /home/raul/NONHUMAN/Psi0/real/teleop
    conda activate psi_deploy
    python probe_pico_controllers.py --duration 10

Prints a single-line dashboard of head + dual-controller state so you can
wave the controllers and watch values change in real time. Verifies that
the installed XRoboToolkit-PC-Service-Pybind exposes every function the
later phases will use.

Phase 0 of the controllers-mode teleop integration. Throwaway — delete
once Fase 1 is validated and the integration is stable.
"""

from __future__ import annotations

import argparse
import sys
import time

import xrobotoolkit_sdk as xrt

from controllers.pico_io import ControllerReceiver


# Functions every later phase will call. If any are missing in the
# installed binary, the integration cannot proceed and we want to know now.
EXPECTED_XRT_FUNCTIONS = [
    "init",
    "close",
    "get_headset_pose",
    "get_left_controller_pose",
    "get_right_controller_pose",
    "get_left_axis",
    "get_right_axis",
    "get_left_trigger",
    "get_right_trigger",
    "get_left_grip",
    "get_right_grip",
    "get_A_button",
    "get_B_button",
    "get_X_button",
    "get_Y_button",
    "get_left_menu_button",
    "get_right_menu_button",
    "get_left_axis_click",
    "get_right_axis_click",
]


def check_xrt_api() -> bool:
    missing = [name for name in EXPECTED_XRT_FUNCTIONS if not hasattr(xrt, name)]
    if missing:
        print("MISSING xrt functions in your installed XRoboToolkit-PC-Service-Pybind:")
        for name in missing:
            print(f"  - xrt.{name}")
        print("\nIntegration cannot proceed until these are exposed.")
        return False
    print("All expected xrt functions are present.")
    return True


def fmt_xyz(mat) -> str:
    if mat is None:
        return "n/a"
    return "[" + ", ".join(f"{v:+.3f}" for v in mat[:3, 3]) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe PICO via XRoboToolkit (Fase 0 — controllers mode).",
    )
    parser.add_argument(
        "--duration", type=float, default=10.0,
        help="Seconds to poll before exiting (default 10).",
    )
    parser.add_argument(
        "--hz", type=float, default=10.0,
        help="Display refresh rate in Hz (default 10).",
    )
    args = parser.parse_args()

    if not check_xrt_api():
        return 1

    # Smoke-test that the controllers/ subpackage at least imports cleanly,
    # so a syntax error in constants.py does not surface only in Fase 1.
    try:
        from controllers import constants  # noqa: F401
        print("controllers/ subpackage imports OK.")
    except Exception as exc:
        print(f"\ncontrollers/ subpackage failed to import: {exc}")
        return 1

    receiver = ControllerReceiver()
    period = 1.0 / args.hz
    deadline = time.time() + args.duration

    print(
        "\nWave the controllers, press buttons, push the sticks. "
        f"Probing for {args.duration:.0f}s...\n"
    )

    try:
        while time.time() < deadline:
            t0 = time.time()
            s = receiver.get_state()

            line = (
                f"head {fmt_xyz(s.head_mat)} | "
                f"L {fmt_xyz(s.left_mat)} "
                f"axis=({s.left_axis[0]:+.2f},{s.left_axis[1]:+.2f}) "
                f"trg={s.left_trigger:.2f} grp={s.left_grip:.2f} | "
                f"R {fmt_xyz(s.right_mat)} "
                f"axis=({s.right_axis[0]:+.2f},{s.right_axis[1]:+.2f}) "
                f"trg={s.right_trigger:.2f} grp={s.right_grip:.2f} | "
                f"btn A={int(s.button_a)} B={int(s.button_b)} "
                f"X={int(s.button_x)} Y={int(s.button_y)} "
                f"mL={int(s.menu_l)} mR={int(s.menu_r)} "
                f"clkL={int(s.axis_click_l)} clkR={int(s.axis_click_r)}"
            )
            sys.stdout.write("\r" + line + "    ")
            sys.stdout.flush()

            elapsed = time.time() - t0
            if elapsed < period:
                time.sleep(period - elapsed)

        print()
        print("\nProbe finished.")
        print("Sanity checklist:")
        print("  - head xyz changes when you move your head")
        print("  - L/R xyz changes when you move each controller")
        print("  - L/R axis values move when you push the sticks")
        print("  - L/R trg/grp values rise to ~1.0 when you squeeze")
        print("  - A/B/X/Y/mL/mR toggle 0↔1 when you press buttons")
        print("If all of the above behave, Fase 0 passes — proceed to Fase 1.")
        return 0
    finally:
        receiver.stop()


if __name__ == "__main__":
    raise SystemExit(main())
