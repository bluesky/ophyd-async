import asyncio
import logging
import re
import time
from unittest.mock import ANY

import numpy
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    ConfigSignal,
    DeviceCollector,
    HintedSignal,
    MockSignalBackend,
    Signal,
    SignalR,
    SignalRW,
    SoftSignalBackend,
    StandardReadable,
    assert_configuration,
    assert_reading,
    assert_value,
    set_and_wait_for_value,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
    wait_for_value,
)
from ophyd_async.core.signal import _SignalCache
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


async def test_signals_equality_raises():
    s1 = epics_signal_rw(int, "pva://pv1", name="signal")
    s2 = epics_signal_rw(int, "pva://pv2", name="signal")
    await s1.connect(mock=True)
    await s2.connect(mock=True)

    with pytest.raises(
        TypeError,
        match=re.escape(
            "Can't compare two Signals, did you mean await signal.get_value() instead?"
        ),
    ):
        s1 == s2
    with pytest.raises(
        TypeError,
        match=re.escape("'>' not supported between instances of 'SignalRW' and 'int'"),
    ):
        s1 > 4


async def test_signal_connect_fails_with_different_backend_on_connection():
    sim_signal = Signal(MockSignalBackend(str))

    with pytest.raises(ValueError):
        await sim_signal.connect(mock=True, backend=MockSignalBackend(int))

    with pytest.raises(ValueError):
        await sim_signal.connect(mock=True, backend=SoftSignalBackend(str))

    with pytest.raises(ValueError):
        await sim_signal.connect(mock=False, backend=MockSignalBackend(str))


async def test_signal_connect_fails_if_different_backend_but_same_by_value():
    initial_backend = MockSignalBackend(str)
    sim_signal = Signal(initial_backend)

    with pytest.raises(ValueError):
        await sim_signal.connect(mock=True, backend=MockSignalBackend(str))

    await sim_signal.connect(mock=True, backend=initial_backend)


async def time_taken_by(coro) -> float:
    start = time.monotonic()
    await coro
    return time.monotonic() - start


async def test_set_and_wait_for_value():
    signal = epics_signal_rw(int, "pva://pv", name="signal")
    await signal.connect(mock=True)
    assert await signal.get_value() == 0
    set_mock_put_proceeds(signal, False)

    async def wait_and_set_proceeds():
        await asyncio.sleep(0.1)
        set_mock_put_proceeds(signal, True)
        await asyncio.sleep(0.01)

    async def check_set_and_wait():
        st = await set_and_wait_for_value(signal, 1, timeout=100)
        await st
        await asyncio.sleep(0.01)

    assert (
        0.1
        < await time_taken_by(
            asyncio.gather(wait_and_set_proceeds(), check_set_and_wait())
        )
        < 0.15
    )
    assert await signal.get_value() == 1


async def test_wait_for_value_with_value():
    signal = epics_signal_rw(str, read_pv="pva://signal", name="signal")
    await signal.connect(mock=True)
    await signal.set("blah")

    with pytest.raises(
        TimeoutError,
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
        TimeoutError,
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
        signal, unused_backend_set = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
    elif signal_method == soft_signal_rw:
        signal = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
    assert signal.source == f"soft://{SIGNAL_NAME}"
    assert isinstance(signal, signal_class)
    assert isinstance(signal._backend, SoftSignalBackend)
    await signal.connect()
    assert (await signal.get_value()) == INITIAL_VALUE


async def test_soft_signal_numpy():
    float_signal = soft_signal_rw(numpy.float64, numpy.float64(1), "float_signal")
    int_signal = soft_signal_rw(numpy.int32, numpy.int32(1), "int_signal")
    await float_signal.connect()
    await int_signal.connect()
    assert (await float_signal.describe())["float_signal"]["dtype"] == "number"
    assert (await int_signal.describe())["int_signal"]["dtype"] == "integer"


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
        with self.add_children_as_readables(HintedSignal):
            self.value = epics_signal_r(float, prefix + "Value")
        with self.add_children_as_readables(ConfigSignal):
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


async def test_signal_connect_logs(caplog):
    caplog.set_level(logging.DEBUG)
    mock_signal_rw = epics_signal_rw(int, "pva://mock_signal", name="mock_signal")
    await mock_signal_rw.connect(mock=True)
    assert caplog.text.endswith("Connecting to mock+pva://mock_signal\n")


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
    cache = _SignalCache(mock_signal_rw._backend, signal=mock_signal_rw)
    assert "Making subscription" in caplog.text
    cache.close()
    assert "Closing subscription on source" in caplog.text
