import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from random import choice
from typing import Any, Generic, TypeVar

import numpy as np
import pytest

from ophyd_async.core import Array1D
from ophyd_async.tango import demo, testing
from ophyd_async.tango.core import DevStateEnum
from ophyd_async.tango.testing import ExampleStrEnum
from ophyd_async.testing import (
    find_free_port,
    float_array_value,
    int_array_value,
)

T = TypeVar("T")

NUM_CHANNELS = 3

# reset_tango_asyncio (PyTango global-executor reset, autouse) moved up to
# tests/system_tests/conftest.py - see its docstring there for why this
# directory alone was no longer broad enough once Tango system tests
# stopped running in their own dedicated CI job/pytest session.


@pytest.fixture(scope="session")
def tango_servers():
    """Start both fixed catalogs of Tango test/demo device servers this repo
    ships (`ophyd_async.tango.testing`/`ophyd_async.tango.demo`'s
    `DEVICE_SERVERS`), shared by every test in this directory - there's
    only one topology now, so there's no reason for individual test modules to
    each start their own subprocesses. Each catalog gets its own free port -
    picked here, since (unlike an EPICS IOC) a Tango TRL bakes the port
    straight into the URL, so downstream fixtures need it to build TRLs."""
    prefix = testing.generate_random_trl_prefix()
    testing_port = find_free_port()
    demo_port = find_free_port()
    testing_process = testing.start_tango_device_servers(
        testing.DEVICE_SERVERS, prefix, str(testing_port)
    )
    demo_process = testing.start_tango_device_servers(
        demo.DEVICE_SERVERS, prefix, str(demo_port), str(NUM_CHANNELS)
    )
    yield prefix, testing_port, demo_port
    demo_process.stop()
    testing_process.stop()
    print(testing_process.output)
    print(demo_process.output)


@pytest.fixture(scope="session")
def tango_test_device(tango_servers) -> str:
    """TRL of the `TestDevice` server: signal-transport/edge-case coverage."""
    prefix, testing_port, _ = tango_servers
    return testing.trl(prefix, testing_port, "basic")


@pytest.fixture(scope="session")
def everything_device_trl(tango_servers) -> str:
    """TRL of the `OneOfEverythingTangoDevice` server: datatype coverage."""
    prefix, testing_port, _ = tango_servers
    return testing.trl(prefix, testing_port, "everything")


@pytest.fixture(scope="session")
def sim_test_context_trls(tango_servers) -> dict[str, str]:
    """TRLs of the demo motor/channel/detector servers backing
    `ophyd_async.tango.demo`, already cross-wired to each other by the
    subprocess itself."""
    prefix, _, demo_port = tango_servers
    return {
        name: testing.trl(prefix, demo_port, name)
        for name in (
            "motor-x",
            "motor-y",
            *(f"channel-{i}" for i in range(1, NUM_CHANNELS + 1)),
            "detector",
        )
    }


def pytest_collection_modifyitems(config, items):
    # Post-move (issue #1321's directory-layout decision:
    # tests/system_tests_tango/ -> tests/system_tests/tango/core/), match on
    # the "tango" path part rather than a substring of the raw path string -
    # a plain "tango" in str(item.fspath) would silently stop matching on
    # Windows, where fspath renders with backslashes, and could also false-
    # positive on an unrelated path containing "tango" as a substring of a
    # longer segment. Using PurePath.parts (OS-appropriate splitting either
    # way, one part per path segment) avoids both. Matches on "tango" alone
    # (not "tango"/"core" specifically) so this stays correct as further
    # subdirectories are added under tests/system_tests/tango/ (e.g. future
    # slices of issue #1321 item 5) without needing another update here.
    # Tango system tests run as part of the regular tests/system_tests CI
    # job now (no more dedicated matrix include/ignore, see #1145 and
    # .github/workflows/ci.yml), which does run on windows-latest - so this
    # skip is the only thing preventing them being collected there for real
    # (tracked separately, #733).
    for item in items:
        parts = PurePath(str(item.fspath)).parts
        if "tango" in parts:
            if sys.platform.startswith(
                "win"
            ):  # expect "win32", but open to a future change: https://mail.python.org/pipermail/patches/2000-May/000648.html
                item.add_marker(
                    pytest.mark.skip(
                        reason="Ophyd-async is currently not tested on Windows + Tango"
                    )
                )


@dataclass
class AttributeData(Generic[T]):
    name: str
    py_type: type
    initial: T
    random_put_values: tuple[T, ...]
    cmd_name: str | None

    def random_value(self):
        return choice(self.random_put_values)


class ArrayData(AttributeData):
    def random_value(self):
        array = self.initial.copy()
        for idx in np.ndindex(array.shape):
            array[idx] = choice(self.random_put_values)
        return array


class SequenceData(AttributeData):
    def random_value(self):
        return [choice(self.random_put_values) for _ in range(len(self.initial))]


def build_everything_signal_info() -> dict[str, AttributeData]:
    """Every field `OneOfEverythingTangoDevice` serves, keyed by attribute name.

    A plain function, not just the body of `everything_signal_info` below, so
    the exhaustive procedural-tier test module (`test_tango_signal_lifecycle.py`)
    can build its `pytest.mark.parametrize` field list at collection time -
    pytest fixtures can't be called directly outside a test, but collection
    needs the field *names* before any fixture would normally run. No device
    server is touched here, so this is safe to call at import time.
    """
    signal_info = {}

    def add_ads(
        name: str,
        tango_type: str,
        py_type: type,
        initial_scalar,
        initial_spectrum,
        choices,
    ):
        scalar_cmd = f"{name}_cmd" if tango_type != "DevUChar" else None
        signal_info[name] = AttributeData(
            name, py_type, initial_scalar, choices, scalar_cmd
        )
        spectrum_cmd = (
            f"{name}_spectrum_cmd"
            if tango_type not in ["DevUChar", "DevState", "DevEnum"]
            else None
        )
        signal_info[f"{name}_spectrum"] = ArrayData(
            f"{name}_spectrum",
            Array1D[py_type],
            initial_spectrum,
            choices,
            spectrum_cmd,
        )
        signal_info[f"{name}_image"] = ArrayData(
            f"{name}_image",
            np.ndarray[Any, np.dtype[py_type]],
            np.vstack((initial_spectrum, initial_spectrum)),
            choices,
            None,
        )

    signal_info["a_str"] = AttributeData(
        "a_str", str, "test_string", ("four", "five", "six"), None
    )
    signal_info["a_str_spectrum"] = SequenceData(
        "a_str_spectrum",
        Sequence[str],
        ("one", "two", "three"),
        ("four", "five", "six"),
        None,
    )
    signal_info["strenum"] = AttributeData(
        name="strenum",
        py_type=ExampleStrEnum,
        initial=ExampleStrEnum.B,
        random_put_values=[
            ExampleStrEnum.A.value,
            ExampleStrEnum.B.value,
            ExampleStrEnum.C.value,
        ],
        cmd_name=None,
    )
    add_ads(
        "a_bool",
        "DevBoolean",
        bool,
        True,
        np.array([False, True], dtype=bool),
        (False, True),
    )
    add_ads("int8", "DevShort", int, 1, int_array_value(np.int8), (1, 2, 3, 4, 5))
    add_ads("uint8", "DevUChar", int, 1, int_array_value(np.uint8), (1, 2, 3, 4, 5))
    add_ads("int16", "DevShort", int, 1, int_array_value(np.int16), (1, 2, 3, 4, 5))
    add_ads("uint16", "DevUShort", int, 1, int_array_value(np.uint16), (1, 2, 3, 4, 5))
    add_ads("int32", "DevLong", int, 1, int_array_value(np.int32), (1, 2, 3, 4, 5))
    add_ads("uint32", "DevULong", int, 1, int_array_value(np.uint32), (1, 2, 3, 4, 5))
    add_ads("int64", "DevLong64", int, 1, int_array_value(np.int64), (1, 2, 3, 4, 5))
    add_ads("uint64", "DevULong64", int, 1, int_array_value(np.uint64), (1, 2, 3, 4, 5))
    add_ads(
        "float32",
        "DevFloat",
        float,
        1.234,
        float_array_value(np.float32),
        (1.234, 2.345, 3.456),
    )
    add_ads(
        "float64",
        "DevDouble",
        float,
        1.234,
        float_array_value(np.float64),
        (1.234, 2.345, 3.456),
    )
    signal_info["my_state"] = AttributeData(
        "my_state",
        DevStateEnum,
        DevStateEnum.INIT,
        random_put_values=[e.name for e in DevStateEnum],
        cmd_name=None,
    )

    return signal_info


@pytest.fixture(scope="module")
def everything_signal_info() -> dict[str, AttributeData]:
    return build_everything_signal_info()


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield loop

    # Cancel all pending tasks
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

    loop.close()
    asyncio.set_event_loop(None)
