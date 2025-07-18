import random
import string
import subprocess
import sys
import time
from pathlib import Path


def generate_random_pv_prefix() -> str:
    """For generating random PV names in test devices."""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + ":"


class TestingIOC:
    """For initialising an IOC in tests."""

    def __init__(self):
        self._db_macros: list[tuple[Path, dict[str, str]]] = []
        self.output = ""

    def add_database(self, db: Path | str, /, **macros: str):
        self._db_macros.append((Path(db), macros))

    def start(self):
        ioc_args = [
            sys.executable,
            "-m",
            "epicscorelibs.ioc",
        ]
        for db, macros in self._db_macros:
            macro_str = ",".join(f"{k}={v}" for k, v in macros.items())
            ioc_args += ["-m", macro_str, "-d", str(db)]
        self._process = subprocess.Popen(
            ioc_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        assert self._process.stdout  # noqa: S101 # this is to make Pylance happy
        start_time = time.monotonic()
        while "iocRun: All initialization complete" not in self.output:
            if time.monotonic() - start_time > 15:
                self.stop()
                raise TimeoutError(f"IOC did not start in time:\n{self.output}")
            self.output += self._process.stdout.readline()

    def stop(self):
        try:
            self.output += self._process.communicate("exit()")[0]
        except ValueError:
            # Someone else already called communicate
            pass
