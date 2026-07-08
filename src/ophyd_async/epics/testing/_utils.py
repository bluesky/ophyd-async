import random
import string
import sys
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass
class Database:
    """One `.db` file to load into a test IOC, under its own macro prefix."""

    path: Path | str
    macros: dict[str, str]


def start_ioc(
    databases: Sequence[Database],
    softioc_args: Sequence[str] = DEFAULT_SOFTIOC_ARGS,
) -> ManagedSubprocess:
    """Start an EPICS IOC subprocess hosting `databases`.

    :param databases: One or more `.db` files to load, each under its own
        macro prefix - e.g. built by `ophyd_async.epics.demo.demo_ioc_args`.
        PV names are never reported back: they're fixed by the `.db` file(s)
        loaded, predictable directly from whatever macro prefix you choose,
        exactly as they would be if you ran `softIoc -d some.db -m "PREFIX:"`
        yourself.
    :param softioc_args: Argv prefix used to host the IOC, defaulting to the
        bundled `epicscorelibs.ioc`. Override to run against a real EPICS
        installation's `softIoc` binary instead, e.g. `["softIoc"]`.
    """
    args = list(softioc_args)
    for db in databases:
        macro_str = ",".join(f"{k}={v}" for k, v in db.macros.items())
        args += ["-m", macro_str, "-d", str(db.path)]
    return start_subprocess(args, _READY_MARKER, stop_input=_STOP_INPUT)
