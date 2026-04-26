"""No-op writers for teleop-only sessions in controller mode.

When the user presses `t` (teleop-only) instead of `s` (record), the
`ControllerTaskmaster._session_init` override instantiates one of these
in place of `writers.IKDataWriter`. The interface (constructor +
positional `write_data` + `close`) is preserved so the rest of the
`run_session` loop and the merge/cleanup paths work without
modification.
"""


class NoOpIKDataWriter:
    """Drop-in replacement for `writers.IKDataWriter` that swallows all
    writes silently.

    The constructor accepts any signature (typically `(dirname,)`) but
    does nothing with it — there is no directory and no file to manage.
    """

    def __init__(self, *args, **kwargs):
        pass

    def write_data(self, *args, **kwargs):
        pass

    def close(self):
        pass
