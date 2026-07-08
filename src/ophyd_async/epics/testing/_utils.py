import random
import string
import sys
from collections.abc import Sequence
from pathlib import Path

from ophyd_async.testing import ManagedSubprocess, start_subprocess

#: Default argv prefix used to host an IOC - the bundled `epicscorelibs.ioc`
#: module. Override (e.g. to `["softIoc"]`) to run against a real EPICS
#: installation's `softIoc` binary instead.
DEFAULT_SOFTIOC_ARGS: Sequence[str] = (sys.executable, "-m", "epicscorelibs.ioc")

_READY_MARKER = "iocRun: All initialization complete"
_STOP_INPUT = "exit()"


def generate_random_pv_prefix() -> str:
    """For generating random PV names in test devices."""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + ":"


def start_ioc(
    subprocess_args: Sequence[str],
    softioc_args: Sequence[str] = DEFAULT_SOFTIOC_ARGS,
) -> ManagedSubprocess:
    """Start an EPICS IOC subprocess.

    :param subprocess_args: The `-m macro -d db` argv, e.g. built by `ioc_args`/
        `ophyd_async.epics.demo.demo_ioc_args`.
    :param softioc_args: Argv prefix used to host the IOC, defaulting to the
        bundled `epicscorelibs.ioc`. Override to run against a real EPICS
        installation's `softIoc` binary instead, e.g. `["softIoc"]`.

    Pins the readiness marker/stop command every such shell uses, so callers
    only ever need to supply the database/macro args.
    """
    return start_subprocess(
        [*softioc_args, *subprocess_args], _READY_MARKER, stop_input=_STOP_INPUT
    )


def ioc_args(databases: Sequence[tuple[Path | str, dict[str, str]]]) -> list[str]:
    """Build the `-m macro -d db` argv for one or more `.db` files.

    Hosts them under caller-chosen macro prefixes.

    Doesn't start anything - pass the result to `start_ioc` (which is where you
    can override which executable actually hosts the IOC). PV names are never
    reported back: they're fixed by the `.db` file(s) loaded, predictable
    directly from whatever macro prefix you pass in `databases`, exactly as they
    would be if you ran `softIoc -d some.db -m "PREFIX:"` yourself.

    :param databases: `(db_path, macros)` pairs - one per `.db` file to load.
    """
    args: list[str] = []
    for db, macros in databases:
        macro_str = ",".join(f"{k}={v}" for k, v in macros.items())
        args += ["-m", macro_str, "-d", str(db)]
    return args
