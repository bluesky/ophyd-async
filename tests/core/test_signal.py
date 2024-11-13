import asyncio
import logging
import re
import time
from asyncio import Event
from unittest.mock import ANY, Mock

import numpy as np
import numpy.typing as npt
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    DeviceCollector,
    SignalR,
    SignalRW,
    SoftSignalBackend,
    StandardReadable,
    assert_configuration,
    assert_reading,
    assert_value,
    callback_on_mock_put,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
    wait_for_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw


def num_occurrences(substring: str, string: str) -> int:
    return len(list(re.finditer(re.escape(substring), string)))


def test_cannot_add_child_to_signal():
    signal = soft_signal_rw(str)
    with pytest.raises(
        AttributeError,
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

    await asyncio.gather(wait_and_set_proceeds(), check_set_and_wait())
    assert await signal.get_value() == 1


async def test_set_and_wait_for_value_different_set_and_read():
    set_signal = epics_signal_rw(int, "pva://set", name="set-signal")
    read_signal = epics_signal_r(str, "pva://read", name="read-signal")
    await set_signal.connect(mock=True)
    await read_signal.connect(mock=True)

    do_read_set = Event()

    callback_on_mock_put(set_signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_read():
        await do_read_set.wait()
        set_mock_value(read_signal, "test")

    async def check_set_and_wait():
        await (
            await set_and_wait_for_other_value(
                set_signal, 1, read_signal, "test", timeout=100
            )
        )

    await asyncio.gather(wait_and_set_read(), check_set_and_wait())
    assert await set_signal.get_value() == 1


async def test_set_and_wait_for_value_different_set_and_read_times_out():
    set_signal = epics_signal_rw(int, "pva://set", name="set-signal")
    read_signal = epics_signal_r(str, "pva://read", name="read-signal")
    await set_signal.connect(mock=True)
    await read_signal.connect(mock=True)

    do_read_set = Event()

    callback_on_mock_put(set_signal, lambda *args, **kwargs: do_read_set.set())

    async def wait_and_set_read():
        await do_read_set.wait()
        set_mock_value(read_signal, "not_test")

    async def check_set_and_wait():
        await (
            await set_and_wait_for_other_value(
                set_signal, 1, read_signal, "test", timeout=0.1
            )
        )

    with pytest.raises(TimeoutError):
        await asyncio.gather(wait_and_set_read(), check_set_and_wait())


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
    assert 0.2 < await t < 1.0


async def test_wait_for_value_with_funcion():
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
    assert 0.2 < await t < 1.0
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


@pytest.fixture
async def mock_signal():
    mock_signal = epics_signal_rw(int, "pva://mock_signal", name="mock_signal")
    await mock_signal.connect(mock=True)
    yield mock_signal


async def test_assert_value(mock_signal: SignalRW):
    set_mock_value(mock_signal, 168)
    await assert_value(mock_signal, 168)


async def test_assert_reaading(mock_signal: SignalRW):
    set_mock_value(mock_signal, 888)
    dummy_reading = {
        "mock_signal": Reading({"alarm_severity": 0, "timestamp": ANY, "value": 888})
    }
    await assert_reading(mock_signal, dummy_reading)


async def test_failed_assert_reaading(mock_signal: SignalRW):
    set_mock_value(mock_signal, 888)
    dummy_reading = {
        "mock_signal": Reading({"alarm_severity": 0, "timestamp": ANY, "value": 88})
    }
    with pytest.raises(AssertionError):
        await assert_reading(mock_signal, dummy_reading)


class DummyReadable(StandardReadable):
    """A demo Readable to produce read and config signal"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.value = epics_signal_r(float, prefix + "Value")
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.mode = epics_signal_rw(str, prefix + "Mode")
            self.mode2 = epics_signal_rw(str, prefix + "Mode2")
        # Set name and signals for read() and read_configuration()
        super().__init__(name=name)


@pytest.fixture
async def mock_readable():
    async with DeviceCollector(mock=True):
        mock_readable = DummyReadable("SIM:READABLE:", name="mock_readable")

    yield mock_readable


async def test_assert_configuration(mock_readable: DummyReadable):
    set_mock_value(mock_readable.value, 123)
    set_mock_value(mock_readable.mode, "super mode")
    set_mock_value(mock_readable.mode2, "slow mode")
    dummy_config_reading = {
        "mock_readable-mode": (
            {
                "alarm_severity": 0,
                "timestamp": ANY,
                "value": "super mode",
            }
        ),
        "mock_readable-mode2": {
            "alarm_severity": 0,
            "timestamp": ANY,
            "value": "slow mode",
        },
    }
    await assert_configuration(mock_readable, dummy_config_reading)


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
        (npt.NDArray[np.float64], "Expected Array1D[dtype], got %s"),
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
