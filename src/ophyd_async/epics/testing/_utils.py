import random
import string
import subprocess
import sys
import time
from pathlib import Path

from aioca import purge_channel_caches

from ophyd_async.core import Device


def generate_random_PV_prefix() -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + ":"


class TestingIOC:
    _dbs: dict[type[Device], list[Path]] = {}
    _prefixes: dict[type[Device], str] = {}

    @classmethod
    def with_database(cls, db: Path | str):  # use as a decorator
        def inner(device_cls: type[Device]):
            cls.database_for(db, device_cls)
            return device_cls

        return inner

    @classmethod
    def database_for(cls, db, device_cls):
        path = Path(db)
        if not path.is_file():
            raise OSError(f"{path} is not a file.")
        if device_cls not in cls._dbs:
            cls._dbs[device_cls] = []
        cls._dbs[device_cls].append(path)

    def prefix_for(self, device_cls):
        # generate random prefix, return existing if already generated
        return self._prefixes.setdefault(device_cls, generate_random_PV_prefix())

    def start_ioc(self):
        ioc_args = [
            sys.executable,
            "-m",
            "epicscorelibs.ioc",
        ]
        for device_cls, dbs in self._dbs.items():
            prefix = self.prefix_for(device_cls)
            for db in dbs:
                ioc_args += ["-m", f"device={prefix}", "-d", str(db)]
        self._process = subprocess.Popen(
            ioc_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        start_time = time.monotonic()
        while "iocRun: All initialization complete" not in (
            self._process.stdout.readline().strip()  # type: ignore
        ):
            if time.monotonic() - start_time > 10:
                try:
                    print(self._process.communicate("exit()")[0])
                except ValueError:
                    # Someone else already called communicate
                    pass
                raise TimeoutError("IOC did not start in time")

    def stop_ioc(self):
        # close backend caches before the event loop
        purge_channel_caches()
        try:
            print(self._process.communicate("exit()")[0])
        except ValueError:
            # Someone else already called communicate
            pass
