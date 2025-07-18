import asyncio
import logging
import re
import time
from asyncio import Event
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, call

import numpy as np
import numpy.typing as npt
import pytest
from bluesky.protocols import Reading
from event_model import DataKey

from ophyd_async.core import (
    Array1D,
    AsyncReadable,
    Device,
    SignalR,
    SignalRW,
    SoftSignalBackend,
    StandardReadable,
    StrictEnum,
    init_devices,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
    wait_for_value,
    walk_devices,
    walk_signal_sources,
)
from ophyd_async.core import (
    StandardReadableFormat as Format,
)
from ophyd_async.core._signal import (
    _SignalCache,  # noqa: PLC2701
)
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw
from ophyd_async.epics.core._signal import get_signal_backend_type  # noqa: PLC2701
from ophyd_async.testing import (
    ExampleEnum,
    ExampleTable,
    OneOfEverythingDevice,
    assert_configuration,
    assert_reading,
    assert_value,
    callback_on_mock_put,
    partial_reading,
    set_mock_put_proceeds,
    set_mock_value,
)

_array_vals = {
    "int8a": np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
    "uint8a": np.array([0, 255, 0, 1, 2, 3, 4], dtype=np.uint8),
    "int16a": np.array([-32768, 32767, 0, 1, 2, 3, 4], dtype=np.int16),
    "uint16a": np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
    "int32a": np.array([-2147483648, 2147483647, 0, 1, 2, 3, 4], dtype=np.int32),
    "uint32a": np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
    "int64a": np.array(
        [-9223372036854775808, 9223372036854775807, 0, 1, 2, 3, 4],
        dtype=np.int64,
    ),
    "uint64a": np.array([0, 18446744073709551615, 0, 1, 2, 3, 4], dtype=np.uint64),
    "float32a": np.array(
        [
            -3.4028235e38,
            3.4028235e38,
            1.1754944e-38,
            1.4012985e-45,
            0.0000000e00,
            1.2340000e00,
            2.3400000e05,
            3.4499999e-06,
        ],
        dtype=np.float32,
    ),
    "float64a": np.array(
        [
            -1.79769313e308,
            1.79769313e308,
            2.22507386e-308,
            4.94065646e-324,
            0.00000000e000,
            1.23400000e000,
            2.34000000e005,
            3.45000000e-006,
        ],
        dtype=np.float64,
    ),
    "boola": np.array([False, False, True]),
}


@pytest.fixture
async def one_of_everything_device():
    device = OneOfEverythingDevice("everything-device")
    await device.connect()
    return device


def num_occurrences(substring: str, string: str) -> int:
    return len(list(re.finditer(re.escape(substring), string)))


def test_cannot_add_child_to_signal():
    signal = soft_signal_rw(str)
    with pytest.raises(
        KeyError,
        match="Cannot add Device or Signal child foo=<.*> of Signal, "
        "make a subclass of Device instead",
    ):
        signal.foo = signal


async def test_signal_connects_to_previous_backend(caplog):
    caplog.set_level(logging.DEBUG)
    signal = soft_signal_rw(int)
    mock_connect = Mock(side_effect=signal._connector.backend.connect)
    signal._connector.backend.connect = mock_connect
    await signal.connect()
    assert mock_connect.call_count == 1
    assert num_occurrences(f"Connecting to {signal.source}", caplog.text) == 1
    await asyncio.gather(signal.connect(), signal.connect(), signal.connect())
    assert mock_connect.call_count == 1
    assert num_occurrences(f"Connecting to {signal.source}", caplog.text) == 1


async def test_signal_connects_with_force_reconnect(caplog):
    caplog.set_level(logging.DEBUG)
    signal = soft_signal_rw(int)
    await signal.connect()
    assert num_occurrences(f"Connecting to {signal.source}", caplog.text) == 1
    await signal.connect(force_reconnect=True)
    assert num_occurrences(f"Connecting to {signal.source}", caplog.text) == 2


async def time_taken_by(coro) -> float:
    start = time.monotonic()
    await coro
    return time.monotonic() - start


async def test_set_and_wait_for_value_same_set_as_read():
    signal = epics_signal_rw(int, "pva://pv", name="signal")
    await signal.connect(mock=True)
    assert await signal.get_value() == 0
    set_mock_put_proceeds(signal, False)

    do_read_set = Event()
    callback_on_mock_put(signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_proceeds():
        await do_read_set.wait()
        set_mock_put_proceeds(signal, True)

    async def check_set_and_wait():
        await (await set_and_wait_for_value(signal, 1, timeout=0.1))

    assert await signal.get_value() == 0
    await asyncio.gather(wait_and_set_proceeds(), check_set_and_wait())
    assert await signal.get_value() == 1


async def test_set_and_wait_for_value_different_set_and_read():
    set_signal = epics_signal_rw(int, "pva://set", name="set-signal")
    match_signal = epics_signal_r(str, "pva://read", name="match-signal")
    await set_signal.connect(mock=True)
    await match_signal.connect(mock=True)

    do_read_set = Event()

    callback_on_mock_put(set_signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_read():
        await do_read_set.wait()
        set_mock_value(match_signal, "test")

    async def check_set_and_wait():
        status = await set_and_wait_for_other_value(
            set_signal,
            1,
            match_signal,
            "test",
            timeout=100,
            wait_for_set_completion=True,
        )
        assert await match_signal.get_value() == "test"
        assert status.done

    await asyncio.gather(wait_and_set_read(), check_set_and_wait())
    assert await set_signal.get_value() == 1


async def test_set_and_wait_behavior_with_wait_for_set_completion_false():
    set_signal = epics_signal_rw(int, "pva://set", name="set-signal")
    match_signal = epics_signal_r(str, "pva://read", name="match-signal")
    await set_signal.connect(mock=True)
    await match_signal.connect(mock=True)
    set_mock_put_proceeds(set_signal, False)

    do_read_set = Event()

    callback_on_mock_put(set_signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_read():
        await do_read_set.wait()
        set_mock_value(match_signal, "test")

    async def check_set_and_wait():
        status = await set_and_wait_for_other_value(
            set_signal,
            1,
            match_signal,
            "test",
            timeout=10,
            wait_for_set_completion=False,
        )
        assert not status.done
        assert await match_signal.get_value() == "test"
        set_mock_put_proceeds(set_signal, True)
        await status
        assert status.done
        assert await set_signal.get_value() == 1

    await asyncio.gather(wait_and_set_read(), check_set_and_wait())
    assert await set_signal.get_value() == 1


async def test_set_and_wait_for_value_different_set_and_read_times_out():
    set_signal = epics_signal_rw(int, "pva://set", name="set-signal")
    match_signal = epics_signal_r(str, "pva://read", name="match-signal")
    await set_signal.connect(mock=True)
    await match_signal.connect(mock=True)

    do_read_set = Event()

    callback_on_mock_put(set_signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_read():
        await do_read_set.wait()
        set_mock_value(match_signal, "not_test")

    async def check_set_and_wait():
        await (
            await set_and_wait_for_other_value(
                set_signal, 1, match_signal, "test", timeout=0.1
            )
        )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.gather(wait_and_set_read(), check_set_and_wait())


@pytest.mark.timeout(3)
async def test_status_of_set_and_wait_for_value():
    set_signal = epics_signal_rw(int, "pva://signal")
    match_signal = epics_signal_rw(int, "pva://match_signal")

    async def set_match_signal_after_delay(value: Any, **kwargs):
        await asyncio.sleep(0.3)
        await match_signal.set(value / 2)

    await set_signal.connect(mock=True)
    await match_signal.connect(mock=True)
    callback_on_mock_put(set_signal, set_match_signal_after_delay)  # type: ignore

    status = await set_and_wait_for_value(set_signal, 2)
    assert status.done

    with pytest.raises(asyncio.TimeoutError):
        status = await set_and_wait_for_value(set_signal, 4, timeout=0.1)

    with pytest.raises(asyncio.TimeoutError):
        status = await set_and_wait_for_value(
            set_signal, 8, timeout=0.1, wait_for_set_completion=False
        )

    status = await set_and_wait_for_other_value(set_signal, 32, match_signal, 16)
    assert status.done

    status = await set_and_wait_for_other_value(
        set_signal, 30, match_signal, 15, wait_for_set_completion=False
    )
    assert not status.done
    await status

    with pytest.raises(asyncio.TimeoutError):
        status = await set_and_wait_for_other_value(
            set_signal, 30, match_signal, -1, timeout=0.5
        )


@pytest.mark.timeout(3)
async def test_callable_match_value_set_and_wait_for_value():
    set_signal = epics_signal_rw(int, "pva://signal")
    match_signal = epics_signal_rw(int, "pva://match_signal")

    async def set_match_signal_after_delay(value: Any, **kwargs):
        await asyncio.sleep(0.3)
        await match_signal.set(value / 2)

    await set_signal.connect(mock=True)
    await match_signal.connect(mock=True)
    callback_on_mock_put(set_signal, set_match_signal_after_delay)  # type: ignore

    def _equals_x(value, x):
        return value == x

    status = await set_and_wait_for_value(
        set_signal, 10, lambda val: _equals_x(val, 10)
    )
    assert status.done

    status = await set_and_wait_for_other_value(
        set_signal, 20, match_signal, lambda val: _equals_x(val, 10)
    )
    assert status.done

    with pytest.raises(asyncio.TimeoutError):
        status = await set_and_wait_for_other_value(
            set_signal, 30, match_signal, lambda val: _equals_x(val, -1), timeout=0.5
        )


async def test_wait_for_value_with_value():
    signal = epics_signal_rw(str, read_pv="pva://signal", name="signal")
    await signal.connect(mock=True)
    await signal.set("blah")

    with pytest.raises(
        asyncio.TimeoutError,
        match="signal didn't match 'something' in 0.1s, last value 'blah'",
    ):
        await wait_for_value(signal, "something", timeout=0.1)
    assert await time_taken_by(wait_for_value(signal, "blah", timeout=2)) < 0.1
    t = asyncio.create_task(
        time_taken_by(wait_for_value(signal, "something else", timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_mock_value(signal, "something else")
    assert 0.1 < await t < 1.0


async def test_wait_for_value_with_function():
    signal = epics_signal_rw(float, read_pv="pva://signal", name="signal")
    await signal.connect(mock=True)
    set_mock_value(signal, 45.8)

    def less_than_42(v):
        return v < 42

    with pytest.raises(
        asyncio.TimeoutError,
        match="signal didn't match less_than_42 in 0.1s, last value 45.8",
    ):
        await wait_for_value(signal, less_than_42, timeout=0.1)
    t = asyncio.create_task(
        time_taken_by(wait_for_value(signal, less_than_42, timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_mock_value(signal, 41)
    assert 0.1 < await t < 1.0
    assert await time_taken_by(wait_for_value(signal, less_than_42, timeout=2)) < 0.1


@pytest.mark.parametrize(
    "signal_method,signal_class",
    [(soft_signal_r_and_setter, SignalR), (soft_signal_rw, SignalRW)],
)
async def test_create_soft_signal(signal_method, signal_class):
    SIGNAL_NAME = "TEST-PREFIX:SIGNAL"
    INITIAL_VALUE = "INITIAL"
    if signal_method == soft_signal_r_and_setter:
        signal, _ = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
    elif signal_method == soft_signal_rw:
        signal = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
    else:
        raise ValueError(signal_method)
    assert signal.source == f"soft://{SIGNAL_NAME}"
    assert isinstance(signal, signal_class)
    await signal.connect()
    assert isinstance(signal._connector.backend, SoftSignalBackend)
    assert (await signal.get_value()) == INITIAL_VALUE


def test_signal_r_cached():
    SIGNAL_NAME = "TEST-PREFIX:SIGNAL"
    INITIAL_VALUE = "INITIAL"
    signal = soft_signal_r_and_setter(str, INITIAL_VALUE, SIGNAL_NAME)[0]
    assert signal._cache is None
    with pytest.raises(RuntimeError, match=r".* not being monitored"):
        signal._backend_or_cache(cached=True)


class MockEnum(StrictEnum):
    GOOD = "Good"
    OK = "Ok"


class DummyReadableArray(StandardReadable):
    """A demo Readable to produce read and config signal"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.int_value = epics_signal_r(int, prefix + "int")
            self.int_array = epics_signal_r(Array1D[np.int8], prefix + "Value")
            self.float_array = epics_signal_r(Array1D[np.float32], prefix + "Value")
        # Set name and signals for read() and read_configuration()
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.str_value = epics_signal_rw(str, prefix + "Value")
            self.strictEnum_value = epics_signal_rw(MockEnum, prefix + "array2")
        super().__init__(name=name)


@pytest.fixture
async def mock_readable():
    async with init_devices(mock=True):
        mock_readable = DummyReadableArray("SIM:READABLE:", name="mock_readable")
    yield mock_readable


async def test_assert_value(mock_readable: DummyReadableArray):
    set_mock_value(mock_readable.int_value, 168)
    await assert_value(mock_readable.int_value, 168)


async def test_assert_reading(mock_readable: DummyReadableArray):
    set_mock_value(mock_readable.int_value, 188)
    set_mock_value(mock_readable.int_array, np.array([1, 2, 4, 7]))
    set_mock_value(mock_readable.float_array, np.array([1.1231, -2.3, 451.15, 6.6233]))

    dummy_reading = {
        "mock_readable-int_value": Reading(
            {"alarm_severity": 0, "timestamp": ANY, "value": 188}
        ),
        "mock_readable-int_array": Reading(
            {"alarm_severity": 0, "timestamp": ANY, "value": [1, 2, 4, 7]}
        ),
        "mock_readable-float_array": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": [1.1231, -2.3, 451.15, 6.6233],
            }
        ),
    }
    await assert_reading(mock_readable, dummy_reading)
    await assert_reading(mock_readable, dummy_reading, full_match=False)


async def test_assert_extra_expected_reading(mock_readable: DummyReadableArray):
    set_mock_value(mock_readable.int_value, 188)
    set_mock_value(mock_readable.int_array, np.array([1, 2, 4, 7]))
    set_mock_value(mock_readable.float_array, np.array([1.1231, -2.3, 451.15, 6.6233]))

    dummy_reading = {
        "mock_readable-int_value": {"value": 188},
        "mock_readable-int_array": {"value": [1, 2, 4, 7]},
        "mock_readable-float_array": {"value": [1.1231, -2.3, 451.15, 6.6233]},
        "bazinga": {"value": 0},
    }
    with pytest.raises(AssertionError, match=r"Right contains 1 more item:\n.*bazinga"):
        await assert_reading(mock_readable, dummy_reading)

    with pytest.raises(AssertionError, match=r"Right contains 1 more item:\n.*bazinga"):
        await assert_reading(mock_readable, dummy_reading, full_match=False)


async def test_assert_partial_reading(mock_readable: DummyReadableArray):
    set_mock_value(mock_readable.int_value, 188)
    set_mock_value(mock_readable.int_array, np.array([1, 2, 4, 7]))
    set_mock_value(mock_readable.float_array, np.array([1.1231, -2.3, 451.15, 6.6233]))

    dummy_reading = {
        "mock_readable-int_value": {"value": 188},
        "mock_readable-int_array": {"value": [1, 2, 4, 7]},
    }
    await assert_reading(mock_readable, dummy_reading, full_match=False)
    with pytest.raises(
        AssertionError, match=r"Left contains 1 more item:\n.*mock_readable-float_array"
    ):
        await assert_reading(mock_readable, dummy_reading)


async def test_assert_reading_optional_fields(
    one_of_everything_device: OneOfEverythingDevice,
):
    # alarm_severity of 0 and timestamp of ANY supplied if none given
    await assert_reading(
        one_of_everything_device.a_int, {"everything-device-a_int": partial_reading(1)}
    )

    with pytest.raises(AssertionError):
        await assert_reading(
            one_of_everything_device.a_int,
            {"everything-device-a_int": {"value": 1, "timestamp": -1}},
        )

    with pytest.raises(AssertionError):
        await assert_reading(
            one_of_everything_device.a_int,
            {"everything-device-a_int": {"value": 1, "alarm_severity": 1}},
        )

    await assert_reading(
        one_of_everything_device.a_int,
        {
            "everything-device-a_int": {
                "value": 1,
                "alarm_severity": 0,
                "timestamp": pytest.approx(time.time(), rel=1e-2),
            }
        },
    )


async def test_assert_configuration_everything(
    one_of_everything_device: OneOfEverythingDevice,
):
    await assert_configuration(
        one_of_everything_device,
        {
            "everything-device-a_int": partial_reading(1),
            "everything-device-a_float": partial_reading(1.234),
            "everything-device-a_str": partial_reading("test_string"),
            "everything-device-a_bool": partial_reading(True),
            "everything-device-a_enum": partial_reading("Bbb"),
            "everything-device-boola": partial_reading(_array_vals["boola"]),
            "everything-device-int8a": partial_reading(_array_vals["int8a"]),
            "everything-device-uint8a": partial_reading(_array_vals["uint8a"]),
            "everything-device-int16a": partial_reading(_array_vals["int16a"]),
            "everything-device-uint16a": partial_reading(_array_vals["uint16a"]),
            "everything-device-int32a": partial_reading(_array_vals["int32a"]),
            "everything-device-uint32a": partial_reading(_array_vals["uint32a"]),
            "everything-device-int64a": partial_reading(_array_vals["int64a"]),
            "everything-device-uint64a": partial_reading(_array_vals["uint64a"]),
            "everything-device-float32a": partial_reading(_array_vals["float32a"]),
            "everything-device-float64a": partial_reading(_array_vals["float64a"]),
            "everything-device-stra": partial_reading(["one", "two", "three"]),
            "everything-device-enuma": partial_reading([ExampleEnum.A, ExampleEnum.C]),
            "everything-device-table": partial_reading(
                ExampleTable(
                    a_bool=np.array([False, False, True, True]),
                    a_int=np.array([1, 8, -9, 32], dtype=np.int32),
                    a_float=np.array([1.8, 8.2, -6.0, 32.9887]),
                    a_str=["Hello", "World", "Foo", "Bar"],
                    a_enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
                ),
            ),
            "everything-device-ndarray": partial_reading(
                np.array([[1, 2, 3], [4, 5, 6]])
            ),
        },
    )


async def test_assert_reading_everything(
    one_of_everything_device: OneOfEverythingDevice,
):
    await assert_reading(one_of_everything_device, {})
    await assert_reading(
        one_of_everything_device.a_int,
        {"everything-device-a_int": partial_reading(1)},
    )
    await assert_reading(
        one_of_everything_device.a_float,
        {"everything-device-a_float": partial_reading(1.234)},
    )
    await assert_reading(
        one_of_everything_device.a_str,
        {
            "everything-device-a_str": partial_reading("test_string"),
        },
    )
    await assert_reading(
        one_of_everything_device.a_bool,
        {"everything-device-a_bool": partial_reading(True)},
    )
    await assert_reading(
        one_of_everything_device.boola,
        {
            "everything-device-boola": partial_reading(_array_vals["boola"]),
        },
    )
    await assert_reading(
        one_of_everything_device.a_enum,
        {
            "everything-device-a_enum": partial_reading(ExampleEnum.B),
        },
    )
    await assert_reading(
        one_of_everything_device.int8a,
        {
            "everything-device-int8a": partial_reading(_array_vals["int8a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.uint8a,
        {
            "everything-device-uint8a": partial_reading(_array_vals["uint8a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.int16a,
        {
            "everything-device-int16a": partial_reading(_array_vals["int16a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.uint16a,
        {
            "everything-device-uint16a": partial_reading(_array_vals["uint16a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.int32a,
        {
            "everything-device-int32a": partial_reading(_array_vals["int32a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.uint32a,
        {
            "everything-device-uint32a": partial_reading(_array_vals["uint32a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.int64a,
        {
            "everything-device-int64a": partial_reading(_array_vals["int64a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.uint64a,
        {
            "everything-device-uint64a": partial_reading(_array_vals["uint64a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.float32a,
        {
            "everything-device-float32a": partial_reading(_array_vals["float32a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.float64a,
        {
            "everything-device-float64a": partial_reading(_array_vals["float64a"]),
        },
    )
    await assert_reading(
        one_of_everything_device.stra,
        {
            "everything-device-stra": partial_reading(["one", "two", "three"]),
        },
    )
    await assert_reading(
        one_of_everything_device.enuma,
        {
            "everything-device-enuma": partial_reading([ExampleEnum.A, ExampleEnum.C]),
        },
    )
    await assert_reading(
        one_of_everything_device.table,
        {
            "everything-device-table": partial_reading(
                ExampleTable(
                    a_bool=np.array([False, False, True, True], np.bool_),
                    a_int=np.array([1, 8, -9, 32], np.int32),
                    a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
                    a_str=["Hello", "World", "Foo", "Bar"],
                    a_enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
                ),
            )
        },
    )
    await assert_reading(
        one_of_everything_device.ndarray,
        {
            "everything-device-ndarray": partial_reading(
                np.array(([1, 2, 3], [4, 5, 6]))
            ),
        },
    )


async def test_assert_reading_default_metadata(
    one_of_everything_device: OneOfEverythingDevice,
):
    await assert_reading(
        one_of_everything_device.a_int,
        {"everything-device-a_int": partial_reading(1)},
    )
    await assert_reading(
        one_of_everything_device.a_int,
        {"everything-device-a_int": {"value": 1, "timestamp": ANY}},
    )
    await assert_reading(
        one_of_everything_device.a_int,
        {
            "everything-device-a_int": {
                "value": 1,
                "timestamp": pytest.approx(time.time(), rel=1e-2),
            }
        },
    )
    await assert_reading(
        one_of_everything_device.a_int,
        {
            "everything-device-a_int": {
                "value": 1,
                "timestamp": pytest.approx(time.time(), rel=1e-2),
                "alarm_severity": 0,
            }
        },
    )
    with pytest.raises(AssertionError):
        await assert_reading(
            one_of_everything_device.a_int,
            {
                "everything-device-a_int": {
                    "value": 1,
                    "timestamp": 2 * time.time(),
                }
            },
        )
    with pytest.raises(AssertionError):
        await assert_reading(
            one_of_everything_device.a_int,
            {"everything-device-a_int": partial_reading(2)},
        )
    with pytest.raises(AssertionError):
        await assert_reading(
            one_of_everything_device.a_int,
            {"everything-device-a_int": {"value": 1, "alarm_severity": 1}},
        )


@pytest.mark.parametrize(
    "int_value, int_array, float_array",
    [
        ([128, np.array([1, 2, 4, 7]), np.array([1.1231, -2.3, 451.15, 6.6233])]),
        ([188, np.array([-5, 2, 4, 7]), np.array([1.1231, -2.3, 451.15, 6.6233])]),
        ([188, np.array([1, 2, 4, 7]), np.array([1.231, -2.3, 451.15, 6.6233])]),
    ],
)
async def test_failed_assert_reading(
    mock_readable: DummyReadableArray, int_value, int_array, float_array
):
    set_mock_value(mock_readable.int_value, 188)
    set_mock_value(mock_readable.int_array, np.array([1, 2, 4, 7]))
    set_mock_value(mock_readable.float_array, np.array([1.1231, -2.3, 451.15, 6.6233]))

    dummy_reading = {
        "mock_readable-int_value": Reading(
            {"alarm_severity": 0, "timestamp": ANY, "value": int_value}
        ),
        "mock_readable-int_array": Reading(
            {"alarm_severity": 0, "timestamp": ANY, "value": int_array}
        ),
        "mock_readable-float_array": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": float_array,
            }
        ),
    }
    with pytest.raises(AssertionError):
        await assert_reading(mock_readable, dummy_reading)


async def test_assert_reading_without_severity():
    class Thing(Device, AsyncReadable):
        async def describe(self) -> dict[str, DataKey]:
            return {}

        async def read(self) -> dict[str, Reading]:
            return {"foo": {"value": 42, "timestamp": 0.1}}

    await assert_reading(Thing(), {"foo": partial_reading(42)})


async def test_assert_configuration(mock_readable: DummyReadableArray):
    set_mock_value(mock_readable.str_value, "haha")
    set_mock_value(mock_readable.strictEnum_value, MockEnum.GOOD)
    dummy_reading = {
        "mock_readable-str_value": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": "haha",
            }
        ),
        "mock_readable-strictEnum_value": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": MockEnum.GOOD,
            }
        ),
    }
    await assert_configuration(mock_readable, dummy_reading)


async def test_assert_value_everything(
    one_of_everything_device: OneOfEverythingDevice,
):
    await assert_value(one_of_everything_device.a_int, 1)
    await assert_value(one_of_everything_device.a_float, 1.234)
    await assert_value(one_of_everything_device.a_str, "test_string")
    await assert_value(one_of_everything_device.a_bool, True)
    # for bools we must provide an array not a list for approx comparison to work
    await assert_value(one_of_everything_device.a_enum, ExampleEnum.B)
    await assert_value(one_of_everything_device.boola, _array_vals["boola"])
    await assert_value(
        one_of_everything_device.int8a,
        _array_vals["int8a"],
    )
    await assert_value(one_of_everything_device.uint8a, _array_vals["uint8a"])
    await assert_value(one_of_everything_device.int16a, _array_vals["int16a"])
    await assert_value(one_of_everything_device.uint16a, _array_vals["uint16a"])
    await assert_value(one_of_everything_device.int32a, _array_vals["int32a"])
    await assert_value(one_of_everything_device.uint32a, _array_vals["uint32a"])
    await assert_value(one_of_everything_device.int64a, _array_vals["int64a"])
    await assert_value(one_of_everything_device.uint64a, _array_vals["uint64a"])
    await assert_value(one_of_everything_device.float32a, _array_vals["float32a"])
    await assert_value(one_of_everything_device.float64a, _array_vals["float64a"])
    await assert_value(one_of_everything_device.stra, ["one", "two", "three"])
    await assert_value(one_of_everything_device.enuma, [ExampleEnum.A, ExampleEnum.C])
    await assert_value(
        one_of_everything_device.table,
        ExampleTable(
            a_bool=np.array([False, False, True, True], np.bool_),
            a_int=np.array([1, 8, -9, 32], np.int32),
            a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
            a_str=["Hello", "World", "Foo", "Bar"],
            a_enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
        ),
    )
    await assert_value(
        one_of_everything_device.ndarray, np.array(([1, 2, 3], [4, 5, 6]))
    )


@pytest.mark.parametrize(
    "str_value, enum_value",
    [
        ("ha", MockEnum.OK),
        ("not funny", MockEnum.GOOD),
    ],
)
async def test_assert_configuraion_fail(
    mock_readable: DummyReadableArray, str_value, enum_value
):
    set_mock_value(mock_readable.str_value, "haha")
    set_mock_value(mock_readable.strictEnum_value, MockEnum.GOOD)
    dummy_reading = {
        "mock_readable-mode": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": str_value,
            }
        ),
        "mock_readable-mode2": Reading(
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": enum_value,
            }
        ),
    }
    with pytest.raises(AssertionError):
        await assert_configuration(mock_readable, dummy_reading)


async def test_signal_get_and_set_logging(caplog):
    caplog.set_level(logging.DEBUG)
    mock_signal_rw = epics_signal_rw(int, "pva://mock_signal", name="mock_signal")
    await mock_signal_rw.connect(mock=True)
    await mock_signal_rw.set(value=0)
    assert "Putting value 0 to backend at source" in caplog.text
    assert "Successfully put value 0 to backend at source" in caplog.text
    await mock_signal_rw.get_value()
    assert "get_value() on source" in caplog.text


async def test_subscription_logs(caplog):
    caplog.set_level(logging.DEBUG)
    mock_signal_rw = epics_signal_rw(int, "pva://mock_signal", name="mock_signal")
    await mock_signal_rw.connect(mock=True)
    cbs = []
    mock_signal_rw.subscribe(cbs.append)
    assert "Making subscription" in caplog.text
    mock_signal_rw.clear_sub(cbs.append)
    assert "Closing subscription on source" in caplog.text


class SomeClass:
    def __init__(self):
        self.some_attribute = "some_attribute"

    def some_function(self):
        pass


@pytest.mark.parametrize(
    "datatype,err",
    [
        (SomeClass, "Can't make converter for %s"),
        (object, "Can't make converter for %s"),
        (dict, "Can't make converter for %s"),
        (npt.NDArray[np.str_], "Expected Array1D[dtype], got %s"),
    ],
)
async def test_signal_unknown_datatype(datatype, err):
    err_str = re.escape(err % datatype)
    with pytest.raises(TypeError, match=err_str):
        await epics_signal_rw(datatype, "pva://mock_signal").connect(mock=True)
    with pytest.raises(TypeError, match=err_str):
        await epics_signal_rw(datatype, "ca://mock_signal").connect(mock=True)
    with pytest.raises(TypeError, match=err_str):
        soft_signal_rw(datatype)


async def test_soft_signal_ndarray_can_change_dtype():
    sig = soft_signal_rw(np.ndarray)
    for dtype in (np.int32, np.float64):
        await sig.set(np.arange(4, dtype=dtype))
        assert (await sig.get_value()).dtype == dtype


@pytest.fixture
def signal_cache() -> _SignalCache[Any]:
    backend = MagicMock()
    signal = MagicMock()
    signal.source = "test_source"
    signal.log.debug = MagicMock()
    cache = _SignalCache(backend, signal)

    # Mock the _valid event to simulate it being set
    cache._valid = AsyncMock()
    cache._valid.wait = AsyncMock()

    return cache


async def test_get_reading_runtime_error(signal_cache: _SignalCache[Any]) -> None:
    with pytest.raises(RuntimeError, match="Monitor not working"):
        await asyncio.wait_for(signal_cache.get_reading(), timeout=1.0)


def test_notify_with_value(signal_cache):
    mock_function = Mock()
    signal_cache._reading = {"value": 42}
    signal_cache._notify(mock_function, want_value=True)
    mock_function.assert_called_once_with(42)


def test_notify_without_value(signal_cache):
    mock_function = Mock()
    signal_cache._reading = {"value": 42}
    signal_cache._signal.name = "test_signal"
    signal_cache._notify(mock_function, want_value=False)
    mock_function.assert_called_once_with({"test_signal": partial_reading(42)})


async def test_notify_runtime_error(signal_cache: _SignalCache[Any]) -> None:
    function = MagicMock()

    with pytest.raises(RuntimeError, match="Monitor not working"):
        await asyncio.wait_for(
            signal_cache._notify(function, want_value=True),  # type: ignore
            timeout=1.0,
        )


def test_signal_backend_throws_type_error() -> None:
    with pytest.raises(TypeError, match="Unsupported protocol: XYZ"):
        get_signal_backend_type("XYZ")  # type: ignore


def test_remove_non_existing_listener():
    signal_rw = soft_signal_rw(int, initial_value=4)
    cbs = []
    assert signal_rw.clear_sub(cbs.append) is None


async def test_walk_devices_returns_all_devices(mock_readable: DummyReadableArray):
    """
    Test that walk_devices returns all child devices with correct dotted paths.
    """

    # Get all devices in the tree
    devices = walk_devices(mock_readable)

    assert devices == {
        "int_value": mock_readable.int_value,
        "int_array": mock_readable.int_array,
        "float_array": mock_readable.float_array,
        "str_value": mock_readable.str_value,
        "strictEnum_value": mock_readable.strictEnum_value,
    }

    # All returned objects should be Device instances
    for dev in devices.values():
        assert isinstance(dev, Device)


async def test_walk_signal_sources_returns_signal_sources(
    mock_readable: DummyReadableArray,
):
    """
    Test that walk_signal_sources returns correct mapping
    of dotted paths to Signal sources.
    """
    sources = walk_signal_sources(mock_readable)

    expected_sources = {
        "int_value": mock_readable.int_value.source,
        "int_array": mock_readable.int_array.source,
        "float_array": mock_readable.float_array.source,
        "str_value": mock_readable.str_value.source,
        "strictEnum_value": mock_readable.strictEnum_value.source,
    }

    assert sources == expected_sources


async def test_can_unsubscribe_from_subscribe_callback():
    signal = soft_signal_rw(float)
    callback = Mock()

    def unsubscribe_if_one(value):
        if value == 1.0:
            signal.clear_sub(callback)

    callback.side_effect = unsubscribe_if_one
    signal.subscribe_value(callback)
    signal.subscribe_value(print)
    await signal.set(1.0)
    await signal.set(2.0)
    assert callback.mock_calls == [call(0.0), call(1.0)]
