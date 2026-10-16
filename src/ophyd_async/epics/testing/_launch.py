"""Launch this repo's EPICS IOC subprocesses.

Kept separate from the `_ioc.py` files (`ophyd_async.epics.testing`'s and
`ophyd_async.epics.demo`'s) deliberately: those are genuinely standalone
(zero `ophyd_async` imports - can be copied into or run from a bare
EPICS-only venv), and importing `ophyd_async.testing` here would break that
if this lived in the same file.

`start_ioc` mirrors `ophyd_async.tango.testing.start_tango_device_servers`'s
shape exactly - generic, doesn't know or care which IOC topology it's
launching.
"""

import random
import string
import sys
from pathlib import Path

from ophyd_async.testing import ManagedSubprocess, start_subprocess

_READY_MARKER = "iocRun: All initialization complete"
_STOP_INPUT = "exit()"


def generate_random_pv_prefix() -> str:
    """For generating random PV names in test devices."""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + ":"


def start_ioc(script: Path, *args: str) -> ManagedSubprocess:
    """Start an EPICS IOC subprocess by running `script` with `args`.

    Mirrors `ophyd_async.tango.testing.start_tango_device_servers`'s shape and
    subprocess handling: rather than building the IOC's full argv inline,
    this always launches a real, independently-runnable file - the exact
    command a human would type by hand, so there's no separate "does this
    even work standalone" code path to keep correct.

    :param script: The script implementing the IOC topology to host, e.g.
        `ophyd_async.epics.demo.IOC` or `ophyd_async.epics.testing.IOC`.
    :param args: Positional args for that script's `__main__`, e.g. `prefix`
        or `prefix, str(num_channels)` - whatever it expects. Overriding
        which executable actually hosts the IOC (defaulting to the bundled
        `epicscorelibs.ioc`) is a command-line-only concern of that script
        itself - pass `--softioc ...` as one of `args` if you need that (see
        the script's own `--help`); this function doesn't thread it through.
    """
    subprocess_args = [sys.executable, str(script), *args]
    return start_subprocess(subprocess_args, _READY_MARKER, stop_input=_STOP_INPUT)
