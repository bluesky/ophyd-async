import asyncio
import re
import time

import pytest

from ophyd_async.core import (
    Signal,
    SignalRW,
    MockSignalBackend,
    set_and_wait_for_value,
    set_mock_put_proceeds,
    set_mock_value,
    wait_for_value,
)


class MySignal(Signal):
    @property
    def source(self) -> str:
        return "me"

    async def connect(self, mock=False):
        pass


def test_signals_equality_raises():
    mock_backend = MockSignalBackend(str, "test")

    s1 = MySignal(mock_backend)
    s2 = MySignal(mock_backend)
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


async def test_set_mock_put_proceeds():
    mock_signal = Signal(MockSignalBackend(str, "test"))
    await mock_signal.connect(mock=True)

    assert mock_signal._backend.put_proceeds.is_set() is True

    set_mock_put_proceeds(mock_signal, False)
    assert mock_signal._backend.put_proceeds.is_set() is False
    set_mock_put_proceeds(mock_signal, True)
    assert mock_signal._backend.put_proceeds.is_set() is True


async def time_taken_by(coro) -> float:
    start = time.monotonic()
    await coro
    return time.monotonic() - start


async def test_wait_for_value_with_value():
    mock_signal = SignalRW(MockSignalBackend(str, "test"))
    mock_signal.set_name("mock_signal")
    await mock_signal.connect(mock=True)
    set_mock_value(mock_signal, "blah")

    with pytest.raises(
        TimeoutError,
        match="mock_signal didn't match 'something' in 0.1s, last value 'blah'",
    ):
        await wait_for_value(mock_signal, "something", timeout=0.1)
    assert await time_taken_by(wait_for_value(mock_signal, "blah", timeout=2)) < 0.1
    t = asyncio.create_task(
        time_taken_by(wait_for_value(mock_signal, "something else", timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_mock_value(mock_signal, "something else")
    assert 0.2 < await t < 1.0


async def test_wait_for_value_with_funcion():
    mock_signal = SignalRW(MockSignalBackend(float, "test"))
    mock_signal.set_name("mock_signal")
    await mock_signal.connect(mock=True)
    set_mock_value(mock_signal, 45.8)

    def less_than_42(v):
        return v < 42

    with pytest.raises(
        TimeoutError,
        match="mock_signal didn't match less_than_42 in 0.1s, last value 45.8",
    ):
        await wait_for_value(mock_signal, less_than_42, timeout=0.1)
    t = asyncio.create_task(
        time_taken_by(wait_for_value(mock_signal, less_than_42, timeout=2))
    )
    await asyncio.sleep(0.2)
    assert not t.done()
    set_mock_value(mock_signal, 41)
    assert 0.2 < await t < 1.0
    assert (
        await time_taken_by(wait_for_value(mock_signal, less_than_42, timeout=2)) < 0.1
    )


async def test_set_and_wait_for_value():
    mock_signal = SignalRW(MockSignalBackend(int, "test"))
    mock_signal.set_name("mock_signal")
    await mock_signal.connect(mock=True)
    set_mock_value(mock_signal, 0)
    set_mock_put_proceeds(mock_signal, False)
    st = await set_and_wait_for_value(mock_signal, 1)
    assert not st.done
    set_mock_put_proceeds(mock_signal, True)
    assert await time_taken_by(st) < 0.1
