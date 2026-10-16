import asyncio
import re
import time

import pytest

from ophyd_async.core import (
    AsyncStatus,
    observe_signals_value,
    observe_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
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


async def test_observe_value_done_status_raises():
    sig, setter = soft_signal_r_and_setter(float)

    async def tick_then_fail():
        await asyncio.sleep(0.01)
        setter(1.0)
        await asyncio.sleep(0.01)
        raise ValueError("status failed")

    recv = []
    status = AsyncStatus(tick_then_fail())
    with pytest.raises(ValueError, match="status failed"):
        async for val in observe_value(sig, done_status=status):
            recv.append(val)
    # Received updates before the status failed
    assert recv == [0.0, 1.0]


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
    start = time.monotonic()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await watch()
        assert recv == [0, 1]
        assert time.monotonic() - start == pytest.approx(0.2, abs=0.05)
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
    start = time.monotonic()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await watch()
        assert recv == [0, 1]
        assert time.monotonic() - start == pytest.approx(0.3, abs=0.05)
    finally:
        t.cancel()


@pytest.mark.timeout(3)
async def test_observe_value_times_out_with_no_external_task():
    done_timeout = 0.3
    sig, setter = soft_signal_r_and_setter(float)

    recv = []

    start = time.monotonic()

    with pytest.raises(asyncio.TimeoutError):
        async for val in observe_value(sig, done_timeout=done_timeout):
            recv.append(time.monotonic() - start)
            setter(val + 1)

    # This is a self-driving busy loop: each iteration refills the queue via
    # setter(), so q.get() never blocks and the done_timeout fires from the
    # manual `monotonic() >= deadline` check. On a dev machine that's >4000
    # iterations in 0.3s; CI is slower, so only require enough to prove the
    # loop actually ran rather than blocking on the first value.
    assert len(recv) > 50

    # The deadline check and this measurement read the same monotonic clock, so
    # `elapsed` can never fall meaningfully *below* done_timeout - the loop only
    # exits once its own clock passes the deadline. The lower bound is therefore
    # the real invariant under test: done_timeout is honoured, the loop does not
    # bail out early. We do NOT pin an upper bound: once the deadline passes,
    # tearing down the busy async-generator (cancelling the in-flight wait_for,
    # clear_sub, the trailing `await asyncio.sleep(0)`) costs a handful of
    # event-loop ticks, and on Windows each ticks a full ~15.6 ms timer quantum,
    # so `elapsed` overshoots by an unbounded, load-dependent amount (0.454s
    # seen in CI). That overshoot is scheduling latency, not a broken timeout;
    # the @pytest.mark.timeout(3) above is the backstop against a runaway loop.
    elapsed = time.monotonic() - start
    assert elapsed >= done_timeout - 0.05, f"Elapsed: {elapsed} Received: {recv}"


async def test_observe_value_uses_correct_timeout():
    sig, _ = soft_signal_r_and_setter(float)

    async def watch(timeout, done_timeout):
        async for _ in observe_value(sig, timeout, done_timeout=done_timeout):
            ...

    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await watch(timeout=0.3, done_timeout=0.15)
    assert time.monotonic() - start == pytest.approx(0.15, abs=0.05)


@pytest.mark.timeout(3)
async def test_observe_signals_value_timeout_message():
    """
    Test creates a queue of 2 signals which update with
    different rate and observe with smaller timeout.
    """
    sig1 = soft_signal_rw(float)
    sig2 = soft_signal_rw(float)
    recv1 = []
    recv2 = []
    time_delay_sec1 = 0.3
    time_delay_sec2 = 0.5
    time_delay = 0.1
    n_updates = 2

    async def tick1():
        for i in range(n_updates):
            sig1.set(i + 10.0)
            await asyncio.sleep(time_delay_sec1)

    async def tick2():
        for i in range(n_updates):
            sig2.set(i + 100.0)
            await asyncio.sleep(time_delay_sec2)

    async def watch(timeout, done_timeout):
        async for signal, value in observe_signals_value(
            sig1, sig2, timeout=timeout, done_timeout=done_timeout
        ):
            if signal is sig1:
                recv1.append(value)
            if signal is sig2:
                recv2.append(value)

    async def main_test(tmo):
        # Run the tickers as explicit tasks so that, once `watch` times out,
        # we can cancel them rather than sleeping out their remaining delays.
        # (`asyncio.gather` propagates `watch`'s TimeoutError but leaves the
        # tickers running as orphaned tasks, which filterwarnings=error would
        # escalate to a failure if they were garbage collected while pending.)
        tickers = [asyncio.create_task(tick1()), asyncio.create_task(tick2())]
        try:
            await watch(timeout=tmo, done_timeout=None)
        finally:
            for ticker in tickers:
                ticker.cancel()
            await asyncio.gather(*tickers, return_exceptions=True)

    with pytest.raises(
        asyncio.TimeoutError,
        match=re.escape(
            f"Timeout Error while waiting {time_delay}s "
            "to update ['soft://', 'soft://']. "
            "Last observed signal and value were"
        ),
    ):
        await main_test(time_delay)

    # Assert first default and set values only
    assert recv1 == [0.0, 10.0]
    assert recv2 == [0.0, 100.0]
