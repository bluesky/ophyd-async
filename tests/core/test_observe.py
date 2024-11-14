import asyncio
import time

import pytest

from ophyd_async.core import AsyncStatus, observe_value, soft_signal_r_and_setter


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


async def test_observe_value_times_out():
    sig, setter = soft_signal_r_and_setter(float)

    async def tick():
        for i in range(5):
            await asyncio.sleep(0.1)
            setter(i + 1)

    recv = []

    async def watch():
        async for val in observe_value(sig):
            recv.append(val)

    t = asyncio.create_task(tick())
    start = time.time()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(watch(), timeout=0.2)
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
        async for val in observe_value(sig):
            time.sleep(0.15)
            recv.append(val)

    t = asyncio.create_task(tick())
    start = time.time()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(watch(), timeout=0.2)
        assert recv == [0, 1]
        assert time.time() - start == pytest.approx(0.3, abs=0.05)
    finally:
        t.cancel()


async def test_observe_value_times_out_with_no_external_task():
    sig, setter = soft_signal_r_and_setter(float)

    recv = []

    async def watch():
        async for val in observe_value(sig):
            recv.append(val)
            setter(val + 1)

    start = time.time()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(watch(), timeout=0.1)
    assert recv
    assert time.time() - start == pytest.approx(0.1, abs=0.05)
