import asyncio
import re
import time

import pytest

from ophyd_async.core import (
    Signal,
    SignalRW,
    SimSignalBackend,
    set_and_wait_for_value,
    set_sim_put_proceeds,
    set_sim_value,
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
    sim_backend = SimSignalBackend(str, "test")

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
    sim_signal = Signal(SimSignalBackend(str, "test"))
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
    sim_signal = SignalRW(SimSignalBackend(str, "test"))
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
    sim_signal = SignalRW(SimSignalBackend(float, "test"))
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
    sim_signal = SignalRW(SimSignalBackend(int, "test"))
    sim_signal.set_name("sim_signal")
    await sim_signal.connect(sim=True)
    set_sim_value(sim_signal, 0)
    set_sim_put_proceeds(sim_signal, False)
    st = await set_and_wait_for_value(sim_signal, 1)
    assert not st.done
    set_sim_put_proceeds(sim_signal, True)
    assert await time_taken_by(st) < 0.1
