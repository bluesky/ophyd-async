import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

RECORD = str(Path(__file__).parent / "db" / "panda.db")

import pytest
from bluesky.run_engine import RunEngine, TransitionError


@pytest.fixture(scope="function")
def RE(request):
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    RE = RunEngine({}, call_returns_result=True, loop=loop)

    def clean_event_loop():
        if RE.state not in ("idle", "panicked"):
            try:
                RE.halt()
            except TransitionError:
                pass
        loop.call_soon_threadsafe(loop.stop)
        RE._th.join()
        loop.close()

    request.addfinalizer(clean_event_loop)
    return RE


@pytest.fixture(scope="module", params=["pva", "ca"])
def pva():
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "epicscorelibs.ioc",
            "-d",
            RECORD,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    time.sleep(2)
    assert not process.poll(), process.stdout.read().decode("utf-8")
    yield process

    process.terminate()


# @pytest.fixture(scope="session")
# def pva():
#     process = subprocess.Popen(
#         ["softIocPVA", "-d", "tests/db/panda.db"],
#         stdout=subprocess.PIPE,
#         stderr=subprocess.STDOUT,
#     )
#     time.sleep(2)
#     assert not process.poll(), process.stdout.read().decode("utf-8")
#     yield process

#     process.terminate()
