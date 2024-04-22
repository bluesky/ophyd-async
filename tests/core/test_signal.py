import asyncio
import re
import time

import numpy
import pytest

from ophyd_async.core import (
    Signal,
    SignalR,
    SignalRW,
    SimSignalBackend,
    set_and_wait_for_value,
    set_sim_put_proceeds,
    set_sim_value,
    soft_signal_r_and_backend,
    soft_signal_rw,
    wait_for_value,
)
from ophyd_async.core.utils import DEFAULT_TIMEOUT


class MySignal(Signal):
    @property
    def source(self) -> str:
        return "me"

    async def connect(self, sim=False, timeout=DEFAULT_TIMEOUT):
        pass


def test_signals_equality_raises():
    sim_backend = SimSignalBackend(str)

    s1 = MySignal(sim_backend)
    s2 = MySignal(sim_backend)
    with pytest.raises(
        TypeError,
        match=re.escape(
            "Can't compare two Signals, did you mean await signal.get_value() instead?"
        ),
    ):
        s1 == s2
    with pytest.raises(
        TypeError,
        match=re.escape("'>' not supported between instances of 'MySignal' and 'int'"),
    ):
        s1 > 4


async def test_set_sim_put_proceeds():
    sim_signal = Signal(SimSignalBackend(str))
    await sim_signal.connect(sim=True)

    assert sim_signal._backend.put_proceeds.is_set() is True

    set_sim_put_proceeds(sim_signal, False)
    assert sim_signal._backend.put_proceeds.is_set() is False
    set_sim_put_proceeds(sim_signal, True)
    assert sim_signal._backend.put_proceeds.is_set() is True


async def time_taken_by(coro) -> float:
    start = time.monotonic()
    await coro
    return time.monotonic() - start


async def test_wait_for_value_with_value():
    sim_signal = SignalRW(SimSignalBackend(str))
    sim_signal.set_name("sim_signal")
    await sim_signal.connect(sim=True)
    set_sim_value(sim_signal, "blah")

    with pytest.raises(
        TimeoutError,
        match="sim_signal didn't match 'something' in 0.1s, last value 'blah'",
    ):
        await wait_for_value(sim_signal, "something", timeout=0.1)
    assert await time_taken_by(wait_for_value(sim_signal, "blah", timeout=2)) < 0.1
    t = asyncio.create_task(
        time_taken_by(wait_for_value(sim_signal, "something else", timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_sim_value(sim_signal, "something else")
    assert 0.2 < await t < 1.0


async def test_wait_for_value_with_funcion():
    sim_signal = SignalRW(SimSignalBackend(float))
    sim_signal.set_name("sim_signal")
    await sim_signal.connect(sim=True)
    set_sim_value(sim_signal, 45.8)

    def less_than_42(v):
        return v < 42

    with pytest.raises(
        TimeoutError,
        match="sim_signal didn't match less_than_42 in 0.1s, last value 45.8",
    ):
        await wait_for_value(sim_signal, less_than_42, timeout=0.1)
    t = asyncio.create_task(
        time_taken_by(wait_for_value(sim_signal, less_than_42, timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_sim_value(sim_signal, 41)
    assert 0.2 < await t < 1.0
    assert (
        await time_taken_by(wait_for_value(sim_signal, less_than_42, timeout=2)) < 0.1
    )


async def test_set_and_wait_for_value():
    sim_signal = SignalRW(SimSignalBackend(int))
    sim_signal.set_name("sim_signal")
    await sim_signal.connect(sim=True)
    set_sim_value(sim_signal, 0)
    set_sim_put_proceeds(sim_signal, False)
    st = await set_and_wait_for_value(sim_signal, 1)
    assert not st.done
    set_sim_put_proceeds(sim_signal, True)
    assert await time_taken_by(st) < 0.1


@pytest.mark.parametrize(
    "signal_method,signal_class",
    [(soft_signal_r_and_backend, SignalR), (soft_signal_rw, SignalRW)],
)
async def test_create_soft_signal(signal_method, signal_class):
    SIGNAL_NAME = "TEST-PREFIX:SIGNAL"
    INITIAL_VALUE = "INITIAL"
    if signal_method == soft_signal_r_and_backend:
        signal, backend = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
    elif signal_method == soft_signal_rw:
        signal = signal_method(str, INITIAL_VALUE, SIGNAL_NAME)
        backend = signal._backend
    assert signal.source == f"soft://{SIGNAL_NAME}"
    assert isinstance(signal, signal_class)
    assert isinstance(signal._backend, SimSignalBackend)
    await signal.connect()
    assert (await signal.get_value()) == INITIAL_VALUE
    # connecting with sim=False uses existing SimSignalBackend
    assert signal._backend is backend


async def test_soft_signal_numpy():
    float_signal = soft_signal_rw(numpy.float64, numpy.float64(1), "float_signal")
    int_signal = soft_signal_rw(numpy.int32, numpy.int32(1), "int_signal")
    await float_signal.connect()
    await int_signal.connect()
    assert (await float_signal.describe())["float_signal"]["dtype"] == "number"
    assert (await int_signal.describe())["int_signal"]["dtype"] == "integer"
