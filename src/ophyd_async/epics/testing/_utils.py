import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from aioca import purge_channel_caches

from ophyd_async.core import Device


@dataclass
class Template:
    path: str | Path
    macros: str = ""  # e.g. "P=MY-DEVICE-NAME:,R=MY-SUFFIX:"


def make_ioc_from_templates(*templates: Template) -> subprocess.Popen[Any]:
    ioc_args = [
        sys.executable,
        "-m",
        "epicscorelibs.ioc",
    ]
    for template in templates:
        if template.macros:
            ioc_args += ["-m", template.macros]
        ioc_args += ["-d", str(template.path)]
    process = subprocess.Popen(
        ioc_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    start_time = time.monotonic()
    while "iocRun: All initialization complete" not in (
        process.stdout.readline().strip()  # type: ignore
    ):
        if time.monotonic() - start_time > 10:
            try:
                print(process.communicate("exit()")[0])
            except ValueError:
                # Someone else already called communicate
                pass
            raise TimeoutError("IOC did not start in time")
    return process


def create_ioc_fixture(*templates: Template, fixture_name: str | None = None):
    def make_ioc():
        process = make_ioc_from_templates(*templates)
        yield process

        # close backend caches before the event loop
        purge_channel_caches()
        try:
            print(process.communicate("exit()")[0])
        except ValueError:
            # Someone else already called communicate
            pass

    return pytest.fixture(make_ioc, scope="module", name=fixture_name)


def create_device_fixture(
    device_cls: type[Device], prefix: str, fixture_name: str | None = None
):
    async def create_device():
        device = device_cls(prefix)
        await device.connect()
        return device

    return pytest.fixture(create_device, name=fixture_name)
