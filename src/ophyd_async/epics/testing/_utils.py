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


def start_ioc(subprocess_args: Sequence[str]) -> ManagedSubprocess:
    """Start an EPICS IOC subprocess.

    Built by `TestingIOC.args`/`ophyd_async.epics.demo.demo_ioc_args`. Pins the
    readiness marker/stop command every `epicscorelibs.ioc` (or real `softIoc`)
    shell uses, so callers only ever need to supply argv.
    """
    return start_subprocess(subprocess_args, _READY_MARKER, stop_input=_STOP_INPUT)


class TestingIOC:
    """Builds the argv for an EPICS IOC test backend.

    Hosts one or more `.db` files under caller-chosen macro prefixes.

    Doesn't start anything itself - pass `.args()` to `start_ioc`. PV names are
    never reported back: they're fixed by the `.db` file(s) loaded, predictable
    directly from whatever macro prefix you pass to `add_database`, exactly as
    they would be if you ran `softIoc -d some.db -m "PREFIX:"` yourself.
    """

    def __init__(self):
        self._db_macros: list[tuple[Path, dict[str, str]]] = []

    def add_database(self, db: Path | str, /, **macros: str):
        self._db_macros.append((Path(db), macros))

    def args(self, softioc_args: Sequence[str] = DEFAULT_SOFTIOC_ARGS) -> list[str]:
        args = list(softioc_args)
        for db, macros in self._db_macros:
            macro_str = ",".join(f"{k}={v}" for k, v in macros.items())
            args += ["-m", macro_str, "-d", str(db)]
        return args
