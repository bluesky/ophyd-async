"""Generic Signal-level lifecycle coverage for `core`/soft signals.

Issue #1321 item 6 ("`core`/soft-signal datatype coverage") of the
system-test rewrite epic. Unlike items 4/5 (EPICS, Tango - see
`tests/system_tests/epics/core/test_epics_signal_lifecycle.py`/
`tests/system_tests/tango/core/test_tango_signal_lifecycle.py`), this isn't a
wholesale replacement of an old file: `OneOfEverythingDevice`/
`ParentOfEverythingDevice` (`ophyd_async.testing`) already have thorough
get/describe coverage (`tests/unit_tests/core/test_signal.py`'s
`test_assert_value_everything`/`test_assert_reading_everything`/
`test_assert_configuration_everything`), and settings round-trip coverage
(`tests/unit_tests/plan_stubs/test_settings.py`) - so the concrete remaining
gap is narrower: a generic `assert_signal_lifecycle`-style get/put/monitor/
describe/locate sweep, matching the pattern already used for EPICS/Tango,
hadn't been written yet. This module is net-new, not a deletion+replacement.

Lands under `tests/unit_tests/core/`, not `tests/system_tests/`: this repo's
`system_tests`/`unit_tests` split is external-process vs. single-process, and
soft signals never leave one process - there's no live backend to system-test
here.

No shared-server restore-in-`finally`/module-scoped-connect tricks like the
EPICS/Tango suites need: those exist there to amortise a real network
connect/discovery cost and to avoid leaving a *shared* live device mutated
for the next test. Soft signals have neither constraint - constructing and
connecting `OneOfEverythingDevice` is a plain in-memory object graph, so a
fresh, function-scoped device per parametrized case is both simpler and
already fast enough.
"""

from typing import Any

import numpy as np
import pytest
from bluesky.protocols import Location

from ophyd_async.core import SignalRW
from ophyd_async.testing import (
    ExampleEnum,
    ExampleSubsetEnum,
    ExampleSupersetEnum,
    ExampleTable,
    MonitorQueue,
    OneOfEverythingDevice,
    ParentOfEverythingDevice,
    approx_value,
)


async def assert_signal_lifecycle(signal: SignalRW, initial_value, put_value) -> None:
    """Exercise get/put/monitor/describe/locate on an already-connected signal."""
    describe_before = await signal.describe()

    with MonitorQueue(signal) as q:
        # get + monitor: initial value arrives on subscribe
        await q.assert_updates(initial_value)

        # locate: `SoftSignalBackend` seeds its setpoint from the initial
        # value at construction (unlike EPICS/Tango, there's no separate
        # "nothing written yet" placeholder to worry about), so both halves
        # already agree with `initial_value` before any set() below.
        location: Location = await signal.locate()
        assert approx_value(initial_value) == location["setpoint"]
        assert approx_value(initial_value) == location["readback"]

        # put + monitor: new value arrives after set()
        await signal.set(put_value)
        await q.assert_updates(put_value)

    # locate again: setpoint and readback have moved to the new value
    location = await signal.locate()
    assert approx_value(put_value) == location["setpoint"]
    assert approx_value(put_value) == location["readback"]

    # describe: dtype/shape is stable across the whole lifecycle - a put
    # never changes what a signal *is*, only its value
    describe_after = await signal.describe()
    assert describe_before == describe_after


def _int_array_put_value(dtype: type) -> np.ndarray:
    # 3-9 fits comfortably in every int dtype OneOfEverythingDevice declares
    # (even uint8), so one value list works for all of them.
    return np.array([9, 8, 7, 6, 5, 4, 3], dtype=dtype)


def _float_array_put_value(dtype: type) -> np.ndarray:
    return np.array([9, 8, 7, 6, 5, 4, 3, 2], dtype=dtype)


# A put value for every field `OneOfEverythingDevice` declares, guaranteed
# distinct from that field's documented initial
# (`src/ophyd_async/testing/_one_of_everything.py`) so the monitor in
# `assert_signal_lifecycle` always sees a genuine change event.
PUT_VALUES: dict[str, Any] = {
    "a_int": 42,
    "a_float": 5.678,
    "a_str": "changed_string",
    "a_bool": False,
    "a_enum": ExampleEnum.C,
    "a_subset_enum": ExampleSubsetEnum.A,
    "a_superset_enum": ExampleSupersetEnum.D,
    "boola": np.array([True, True, False]),
    "int8a": _int_array_put_value(np.int8),
    "uint8a": _int_array_put_value(np.uint8),
    "int16a": _int_array_put_value(np.int16),
    "uint16a": _int_array_put_value(np.uint16),
    "int32a": _int_array_put_value(np.int32),
    "uint32a": _int_array_put_value(np.uint32),
    "int64a": _int_array_put_value(np.int64),
    "uint64a": _int_array_put_value(np.uint64),
    "float32a": _float_array_put_value(np.float32),
    "float64a": _float_array_put_value(np.float64),
    # Same length as the field's documented initial (3 elements for `stra`,
    # 4 rows for `table`) - describe()'s `shape` for a variable-length
    # Sequence/Table tracks the *current* value's length, unlike EPICS's
    # fixed-max-length arrays, so changing element count would (correctly)
    # change `shape` too and break the describe-is-stable-across-a-put
    # invariant `assert_signal_lifecycle` checks. That invariant is about a
    # put never changing a signal's *datatype*, not about every value of a
    # variable-length type describing identically - so keep length fixed
    # here rather than weaken the shared helper for this one quirk.
    "stra": ["four", "five", "six"],
    "enuma": [ExampleEnum.B, ExampleEnum.A],
    "table": ExampleTable(
        a_bool=np.array([True, False, True, True], np.bool_),
        a_int=np.array([9, -3, 44, 0], np.int32),
        a_float=np.array([0.5, -12.25, 3.75, 100.0], np.float64),
        a_str=["Foo", "Bar", "Baz", "Qux"],
        a_enum=[ExampleEnum.C, ExampleEnum.A, ExampleEnum.B, ExampleEnum.C],
    ),
    "ndarray": np.array([[9, 8, 7], [6, 5, 4]]),
}


# Every field OneOfEverythingDevice declares, built from a throwaway
# unconnected instance so the parametrize list exists at collection time
# (before any fixture, including one_of_everything_device below, has run) -
# matching the same "exhaustive, not curated" shape EPICS/Tango's own
# lifecycle suites use. Constructing (not connecting) is instant - there's no
# live backend to discover here, unlike Tango's equivalent
# `build_everything_signal_info`.
ALL_FIELDS = sorted(name for name, _ in OneOfEverythingDevice().children())


def test_put_values_cover_every_field():
    """Fails loudly if a new field is ever added to `OneOfEverythingDevice`
    without a corresponding entry here, rather than the sweep below silently
    never parametrizing over it."""
    assert set(PUT_VALUES) == set(ALL_FIELDS)


@pytest.fixture
async def one_of_everything_device() -> OneOfEverythingDevice:
    device = OneOfEverythingDevice("everything-device")
    await device.connect()
    return device


@pytest.mark.parametrize("field", ALL_FIELDS)
async def test_signal_lifecycle(
    one_of_everything_device: OneOfEverythingDevice, field: str
):
    signal = getattr(one_of_everything_device, field)
    initial_value = await signal.get_value()
    put_value = PUT_VALUES[field]
    await assert_signal_lifecycle(signal, initial_value, put_value)


@pytest.fixture
async def parent_of_everything_device() -> ParentOfEverythingDevice:
    device = ParentOfEverythingDevice("parent-device")
    await device.connect()
    return device


async def test_nested_signal_lifecycle(
    parent_of_everything_device: ParentOfEverythingDevice,
):
    """The lifecycle helper generalises unchanged to signals nested under a
    plain sub-`Device` (`.child`), a `DeviceVector` entry (`.vector[...]`),
    and a Device's own top-level `SignalRW` (`.sig_rw`) - not just a flat
    device's direct children.

    Only a couple of representative fields per container, not the full 22 -
    `test_signal_lifecycle` above already sweeps every datatype exhaustively
    at the top level, so this is checking that nesting itself doesn't break
    the lifecycle, not re-proving datatype coverage.
    """
    device = parent_of_everything_device
    for signal, initial, put in [
        (device.child.a_int, 1, 42),
        (device.vector[1].a_int, 1, 42),
        (device.vector[3].a_int, 1, 42),
        (device.sig_rw, "Top level SignalRW", "changed"),
    ]:
        await assert_signal_lifecycle(signal, initial, put)


async def test_signal_error_paths(one_of_everything_device: OneOfEverythingDevice):
    """Core's error semantics genuinely differ from EPICS/Tango here, not by
    omission: `SoftSignalBackend`'s `EnumSoftConverter.write_value` calls the
    enum class directly (`self.datatype(value)`), so both a wrong Python
    type and a right-type-wrong-choice raise the same `ValueError` (plain
    `Enum.__call__` behaviour) - there's no separate `TypeError` case to
    distinguish here, unlike Tango's converter which checks type before
    value (`test_signal_error_paths` in the Tango lifecycle suite).
    """
    with pytest.raises(ValueError, match="is not a valid"):
        await one_of_everything_device.a_enum.set(0)  # type: ignore
    with pytest.raises(ValueError, match="is not a valid"):
        await one_of_everything_device.a_enum.set("NOT_A_REAL_CHOICE")  # type: ignore
