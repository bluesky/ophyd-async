import random
import string
import sys
from pathlib import Path

from ophyd_async.testing import SubprocessSpec


def generate_random_pv_prefix() -> str:
    """For generating random PV names in test devices."""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + ":"


class TestingIOC:
    """Builds the `SubprocessSpec` for an `epicscorelibs.ioc` test IOC.

    Doesn't start anything itself - pass `.spec()` to
    `ophyd_async.testing.start_subprocess`. PV names are never reported back: they're
    fixed by the `.db` file(s) loaded, predictable directly from whatever macro
    prefix you pass to `add_database`, exactly as they would be if you ran
    `softIoc -d some.db -m "PREFIX:"` yourself.
    """

    def __init__(self):
        self._db_macros: list[tuple[Path, dict[str, str]]] = []

    def add_database(self, db: Path | str, /, **macros: str):
        self._db_macros.append((Path(db), macros))

    def spec(self) -> SubprocessSpec:
        args = [sys.executable, "-m", "epicscorelibs.ioc"]
        for db, macros in self._db_macros:
            macro_str = ",".join(f"{k}={v}" for k, v in macros.items())
            args += ["-m", macro_str, "-d", str(db)]
        return SubprocessSpec(
            args=args,
            ready_marker="iocRun: All initialization complete",
            stop_input="exit()",
        )
