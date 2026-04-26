#!/usr/bin/env python3
"""Validate that the PICO headset is reachable from the host."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from dataclasses import dataclass

import numpy as np

try:
    import xrobotoolkit_sdk as xrt
except ImportError as exc:  # pragma: no cover - runtime environment specific
    print(
        "Failed to import xrobotoolkit_sdk. Activate `psi_deploy` and make sure "
        "XRoboToolkit-PC-Service-Pybind is installed.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


DEFAULT_STREAM_PORT = 12345


@dataclass
class TrackingReport:
    head_valid: bool
    left_hand_valid: bool
    right_hand_valid: bool
    head_updates: int
    left_hand_updates: int
    right_hand_updates: int
    last_head_pose: np.ndarray | None
    last_left_hand_shape: tuple[int, ...] | None
    last_right_hand_shape: tuple[int, ...] | None


def _to_float_array(value) -> np.ndarray:
    return np.asarray(value, dtype=np.float64)


def _is_valid_pose7(value) -> bool:
    arr = _to_float_array(value)
    return arr.shape == (7,) and np.all(np.isfinite(arr)) and np.any(np.abs(arr) > 1e-6)


def _is_valid_hand_state(value) -> bool:
    arr = _to_float_array(value)
    return (
        arr.ndim == 2
        and arr.shape[1] >= 3
        and np.all(np.isfinite(arr[:, :3]))
        and np.any(np.abs(arr[:, :3]) > 1e-6)
    )


def _count_updates(previous: np.ndarray | None, current: np.ndarray, eps: float) -> int:
    if previous is None or previous.shape != current.shape:
        return 0
    delta = np.max(np.abs(current - previous))
    return int(delta > eps)


def _sample_tracking(duration_s: float, poll_hz: float, eps: float) -> TrackingReport:
    deadline = time.time() + duration_s
    sleep_s = 1.0 / poll_hz

    head_valid = False
    left_hand_valid = False
    right_hand_valid = False
    head_updates = 0
    left_hand_updates = 0
    right_hand_updates = 0

    prev_head = None
    prev_left = None
    prev_right = None
    last_head = None
    last_left_shape = None
    last_right_shape = None

    while time.time() < deadline:
        head_pose = _to_float_array(xrt.get_headset_pose())
        left_hand = _to_float_array(xrt.get_left_hand_tracking_state())
        right_hand = _to_float_array(xrt.get_right_hand_tracking_state())

        if _is_valid_pose7(head_pose):
            head_valid = True
            head_updates += _count_updates(prev_head, head_pose, eps)
            prev_head = head_pose.copy()
            last_head = head_pose.copy()

        if _is_valid_hand_state(left_hand):
            left_hand_valid = True
            left_hand_updates += _count_updates(prev_left, left_hand[:, :3], eps)
            prev_left = left_hand[:, :3].copy()
            last_left_shape = left_hand.shape

        if _is_valid_hand_state(right_hand):
            right_hand_valid = True
            right_hand_updates += _count_updates(prev_right, right_hand[:, :3], eps)
            prev_right = right_hand[:, :3].copy()
            last_right_shape = right_hand.shape

        time.sleep(sleep_s)

    return TrackingReport(
        head_valid=head_valid,
        left_hand_valid=left_hand_valid,
        right_hand_valid=right_hand_valid,
        head_updates=head_updates,
        left_hand_updates=left_hand_updates,
        right_hand_updates=right_hand_updates,
        last_head_pose=last_head,
        last_left_hand_shape=last_left_shape,
        last_right_hand_shape=last_right_shape,
    )


def _check_stream_port(pico_ip: str, port: int, timeout_s: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((pico_ip, port), timeout=timeout_s):
            return True, f"TCP connection to {pico_ip}:{port} succeeded"
    except OSError as exc:
        return False, f"TCP connection to {pico_ip}:{port} failed: {exc}"


def _format_pose(pose: np.ndarray | None) -> str:
    if pose is None:
        return "n/a"
    xyz = ", ".join(f"{value:.3f}" for value in pose[:3])
    quat = ", ".join(f"{value:.3f}" for value in pose[3:])
    return f"xyz=[{xyz}] quat=[{quat}]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check PICO tracking via XRoboToolkit and the TCP stream port used by teleop."
    )
    parser.add_argument("--pico-ip", required=True, help="PICO headset Wi-Fi IP address")
    parser.add_argument(
        "--stream-port",
        type=int,
        default=DEFAULT_STREAM_PORT,
        help=f"PICO stream port used by PicoIRStreamer (default: {DEFAULT_STREAM_PORT})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="Seconds to poll tracking data before summarizing",
    )
    parser.add_argument(
        "--poll-hz",
        type=float,
        default=20.0,
        help="Tracking poll rate in Hz",
    )
    parser.add_argument(
        "--socket-timeout",
        type=float,
        default=2.0,
        help="Timeout in seconds for the TCP port probe",
    )
    parser.add_argument(
        "--motion-eps",
        type=float,
        default=1e-4,
        help="Minimum value change considered a tracking update",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Keep retrying until tracking and stream both become available",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=60.0,
        help="Maximum seconds to wait when --wait is enabled",
    )
    args = parser.parse_args()

    deadline = time.time() + args.wait_timeout
    attempt = 0
    while True:
        attempt += 1
        print(f"Attempt {attempt}: initializing XRoboToolkit SDK...")
        xrt.init()
        try:
            print("Sampling headset and hand tracking...")
            report = _sample_tracking(
                duration_s=args.duration,
                poll_hz=args.poll_hz,
                eps=args.motion_eps,
            )
        finally:
            xrt.close()

        print()
        print("Tracking summary")
        print(f"- Head pose valid: {report.head_valid}")
        print(f"- Left hand valid: {report.left_hand_valid}")
        print(f"- Right hand valid: {report.right_hand_valid}")
        print(f"- Head updates seen: {report.head_updates}")
        print(f"- Left hand updates seen: {report.left_hand_updates}")
        print(f"- Right hand updates seen: {report.right_hand_updates}")
        print(f"- Last head pose: {_format_pose(report.last_head_pose)}")
        print(f"- Left hand array shape: {report.last_left_hand_shape}")
        print(f"- Right hand array shape: {report.last_right_hand_shape}")

        print()
        print("Stream summary")
        stream_ok, stream_msg = _check_stream_port(
            pico_ip=args.pico_ip,
            port=args.stream_port,
            timeout_s=args.socket_timeout,
        )
        print(f"- {stream_msg}")

        tracking_ok = report.head_valid and (report.left_hand_valid or report.right_hand_valid)
        updates_ok = report.head_updates > 0 or report.left_hand_updates > 0 or report.right_hand_updates > 0

        print()
        if tracking_ok and stream_ok:
            print("PICO looks reachable from the laptop.")
            if not updates_ok:
                print(
                    "Tracking is present but did not change during sampling. Move the headset or hands and rerun if needed."
                )
            return 0

        print("PICO validation failed.")
        if not tracking_ok:
            print(
                "- XRoboToolkit is not receiving valid tracking. Check that the PICO app has Head/Controller/Hand enabled and Send toggled on."
            )
        if not stream_ok:
            print(
                "- The headset is not listening on the stream port. In the PICO app, open Remote Vision Session, select ZEDMINI, press Listen, and enter the laptop Wi-Fi IP."
            )

        if not args.wait:
            return 1

        if time.time() >= deadline:
            print(f"Gave up after waiting {args.wait_timeout:.1f}s.")
            return 1

        print("Waiting 2 seconds before retrying...")
        print()
        time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
