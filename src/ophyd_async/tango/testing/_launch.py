"""Launch, and build TRLs for, this repo's Tango device server subprocesses.

Kept separate from `_tango_device_servers.py` (this package's and
`ophyd_async.tango.demo`'s) deliberately: those two files are genuinely
standalone (zero `ophyd_async` imports - can be copied into or run from a
bare PyTango venv), and importing `ophyd_async.testing` here would break
that if this lived in the same file.

`start_tango_device_servers` mirrors `ophyd_async.epics.testing.start_ioc`'s
shape exactly - generic, doesn't know or care which catalog it's launching.
"""

import sys
from pathlib import Path

from ophyd_async.testing import ManagedSubprocess, start_subprocess

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"


def start_tango_device_servers(script: Path, *args: str) -> ManagedSubprocess:
    """Start a Tango device servers subprocess by running `script` with `args`.

    Generic: doesn't know or care which catalog `script` is - e.g.
    `ophyd_async.tango.testing.DEVICE_SERVERS` (this package's fixed
    `basic`/`everything` catalog) or `ophyd_async.tango.demo.DEVICE_SERVERS`
    (motor/channel/detector). Invoked with the current interpreter, not
    `-m ophyd_async...`, so the exact same argv works verbatim from a venv
    that doesn't have `ophyd_async` installed at all. If you need a different
    Tango install/version, run `script` with that venv's python directly
    instead of going through this function - same as any other standalone
    script.

    :param script: The script implementing the device server catalog to host.
    :param args: Positional args for that script's `__main__`, e.g.
        `(prefix, str(port))` or `(prefix, str(port), str(num_channels))` -
        whatever that particular catalog's script expects. You choose
        `port` yourself, e.g. via `ophyd_async.testing.find_free_port`, and
        need to hang onto it to build TRLs afterwards (see `trl` below).
    """
    return start_subprocess(
        [sys.executable, str(script), *args],
        _READY_MARKER,
        # MultiDeviceTestContext's own startup timeout is 30s; give the outer
        # readiness wait some headroom above that rather than racing it.
        startup_timeout=45.0,
        stop_input=None,  # each catalog's __main__ block exits on stdin EOF
    )


def trl(prefix: str, port: int, device_name: str) -> str:
    """Build the TRL a device server subprocess serves `device_name` at."""
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"
