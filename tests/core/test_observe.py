import asyncio
import time

import pytest

from ophyd_async.core import (
    AsyncStatus,
    observe_signals_value,
    observe_value,
    soft_signal_r_and_setter,
)


async def test_observe_value_working_correctly():
    sig, setter = soft_signal_r_and_setter(float)

    async def tick():
        for i in range(2):
            await asyncio.sleep(0.01)
            setter(i + 1)

    recv = []
    status = AsyncStatus(tick())
    async for val in observe_value(sig, done_status=status):
        recv.append(val)
    assert recv == [0, 1, 2]
    await status


async def test_observes_signals_values_working_correctly():
    sig1, setter1 = soft_signal_r_and_setter(float)
    sig2, setter2 = soft_signal_r_and_setter(float)

    async def tick():
        for i in range(2):
            await asyncio.sleep(0.01)
            setter1(i + 1)
            setter2(i + 10)

    recv1 = []
    recv2 = []
    status = AsyncStatus(tick())
    async for signal, value in observe_signals_value(sig1, sig2, done_status=status):
        if signal is sig1:
            recv1.append(value)
        elif signal is sig2:
            recv2.append(value)
    assert recv1 == [0, 1, 2] and recv2 == [0, 10, 11]
    await status


async def test_observe_value_times_out():
    sig, setter = soft_signal_r_and_setter(float)

    async def tick():
        for i in range(5):
            await asyncio.sleep(0.1)
            setter(i + 1)

    recv = []

    async def watch():
        async for val in observe_value(sig, done_timeout=0.2):
            recv.append(val)

    t = asyncio.create_task(tick())
    start = time.time()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await watch()
        assert recv == [0, 1]
        assert time.time() - start == pytest.approx(0.2, abs=0.05)
    finally:
        t.cancel()


async def test_observe_value_times_out_with_busy_sleep():
    sig, setter = soft_signal_r_and_setter(float)

    async def tick():
        for i in range(5):
            await asyncio.sleep(0.1)
            setter(i + 1)

    recv = []

    async def watch():
        async for val in observe_value(sig, done_timeout=0.2):
            # This is a test to prove a subtle timing bug where the inner loop
            # of observe_value was blocking the event loop.
            time.sleep(0.15)
            recv.append(val)

    t = asyncio.create_task(tick())
    # Let it get started so we get our first update
    # This is needed to fix for python 3.12, otherwise the task
    # gets starved by the busy sleep
    await asyncio.sleep(0.05)
    start = time.time()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await watch()
        assert recv == [0, 1]
        assert time.time() - start == pytest.approx(0.3, abs=0.05)
    finally:
        t.cancel()


async def test_observe_value_times_out_with_no_external_task():
    sig, setter = soft_signal_r_and_setter(float)

    recv = []

    async def watch(done_timeout):
        async for val in observe_value(sig, done_timeout=done_timeout):
            recv.append(val)
            setter(val + 1)

    start = time.time()
    with pytest.raises(asyncio.TimeoutError):
        await watch(done_timeout=0.1)
    assert recv
    assert time.time() - start == pytest.approx(0.1, abs=0.05)


async def test_observe_value_uses_correct_timeout():
    sig, _ = soft_signal_r_and_setter(float)

    async def watch(timeout, done_timeout):
        async for _ in observe_value(sig, timeout, done_timeout=done_timeout):
            ...

    start = time.time()
    with pytest.raises(asyncio.TimeoutError):
        await watch(timeout=0.3, done_timeout=0.15)
    assert time.time() - start == pytest.approx(0.15, abs=0.05)
