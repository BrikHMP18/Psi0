"""Controller-mode teleop subpackage.

Implements PICO-controllers-based teleoperation for the Unitree G1, sharing
the rest of the data-collection pipeline with the hand-tracking flow in
`real/teleop/`. Activated via `real/teleop/teleop_controllers.py` (added in
later phases). Phase 0 ships only `ControllerReceiver` + `constants`.
"""
