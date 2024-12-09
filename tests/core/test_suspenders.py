import asyncio
import time
from pathlib import Path
from typing import Annotated as A

import bluesky.plan_stubs as bps
import pytest
from bluesky.suspenders import (
    SuspendBoolHigh,
    SuspendBoolLow,
    SuspendCeil,
    SuspendFloor,
    SuspendInBand,
    SuspendOutBand,
    SuspendWhenOutsideBand,
)
from bluesky.utils import Msg

from ophyd_async.core import SignalRW
from ophyd_async.epics.core import EpicsDevice, PvSuffix, epics_signal_rw
from ophyd_async.epics.testing import TestingIOC

HERE = Path(__file__).resolve().parent


class SuspenderTestDevice(EpicsDevice):
    signal: A[SignalRW[int], PvSuffix("SIGNAL")]
    resume_signal: A[SignalRW[int], PvSuffix("RESUMEVAL")]
    fail_signal: A[SignalRW[int], PvSuffix("FAILVAL")]
    resume_time_signal: A[SignalRW[int], PvSuffix("RESUMETIME")]
    fail_time_signal: A[SignalRW[int], PvSuffix("FAILTIME")]
    counter_signal: A[SignalRW[int], PvSuffix("COUNTER")]


@pytest.fixture(scope="module")
def ioc():
    ioc = TestingIOC()
    ioc.database_for(HERE / "suspend.db", SuspenderTestDevice)
    ioc.start_ioc()
    yield ioc
    ioc.stop_ioc()


@pytest.fixture
async def suspend_device(ioc):
    device = SuspenderTestDevice(ioc.prefix_for(SuspenderTestDevice))
    await device.connect()
    return device


PARAMETRIZE_SUSPENDERS = pytest.mark.parametrize(
    "klass,sc_args,resume_val,fail_val,deprecated",
    [
        (SuspendBoolHigh, (), 0, 1, False),
        (SuspendBoolLow, (), 1, 0, False),
        (SuspendFloor, (0.5,), 1, 0, False),
        (SuspendCeil, (0.5,), 0, 1, False),
        (SuspendWhenOutsideBand, (0.5, 1.5), 1, 0, False),
        (SuspendInBand, (0.5, 1.5), 1, 0, True),  # renamed to WhenOutsideBand
        (SuspendOutBand, (0.5, 1.5), 0, 1, True),
    ],
)


@PARAMETRIZE_SUSPENDERS
def test_suspender_installed_in_plan(
    klass, sc_args, deprecated, resume_val, fail_val, RE, suspend_device
):
    sleep_time = 0.2
    fail_time = 0.1
    resume_time = 0.5
    wait_time = 0.2
    if deprecated:
        with pytest.warns(UserWarning):
            suspender = klass(
                suspend_device.signal, *sc_args, sleep=wait_time, is_async=True
            )
    else:
        suspender = klass(
            suspend_device.signal, *sc_args, sleep=wait_time, is_async=True
        )

    def plan():
        yield from bps.abs_set(suspend_device.resume_signal, resume_val, wait=True)
        yield from bps.abs_set(suspend_device.fail_signal, fail_val, wait=True)
        yield from bps.abs_set(
            suspend_device.resume_time_signal, resume_time, wait=True
        )
        yield from bps.abs_set(suspend_device.fail_time_signal, fail_time, wait=True)
        yield from bps.abs_set(suspend_device.signal, resume_val, wait=True)
        yield from bps.abs_set(suspend_device.counter_signal, 0, wait=True)
        RE.install_suspender(suspender)
        yield from bps.checkpoint()
        yield from bps.sleep(sleep_time)

    start = time.time()
    RE(plan())
    stop = time.time()
    delta = stop - start
    assert delta >= resume_time + sleep_time + wait_time


@PARAMETRIZE_SUSPENDERS
async def test_suspender_installed_outside_plan(
    klass, sc_args, deprecated, resume_val, fail_val, RE, suspend_device
):
    sleep_time = 0.2
    fail_time = 0.1
    resume_time = 0.5
    wait_time = 0.2
    if deprecated:
        with pytest.warns(UserWarning):
            suspender = klass(
                suspend_device.signal, *sc_args, sleep=wait_time, is_async=True
            )
    else:
        suspender = klass(
            suspend_device.signal, *sc_args, sleep=wait_time, is_async=True
        )

    RE.install_suspender(suspender)
    scan = [Msg("checkpoint"), Msg("sleep", None, sleep_time)]
    await suspend_device.resume_signal.set(resume_val, wait=True)
    await suspend_device.fail_signal.set(fail_val, wait=True)
    await suspend_device.resume_time_signal.set(resume_time, wait=True)
    await suspend_device.fail_time_signal.set(fail_time, wait=True)
    await suspend_device.signal.set(resume_val, wait=True)
    await suspend_device.counter_signal.set(0, wait=True)
    start = time.time()
    RE(scan)
    stop = time.time()
    delta = stop - start
    assert delta >= resume_time + sleep_time + wait_time


@PARAMETRIZE_SUSPENDERS
@pytest.mark.parametrize("task_in_plan", [True, False])
async def test_suspension_from_async_task(
    klass, sc_args, deprecated, resume_val, fail_val, task_in_plan, RE, ioc
):
    sleep_time = 0.2
    fail_time = 0.1
    resume_time = 0.5
    wait_time = 0.2

    signal = epics_signal_rw(
        float, f"{ioc.prefix_for(SuspenderTestDevice)}STATICSIGNAL"
    )
    await signal.connect()
    await signal.set(resume_val)  # set to initial non-suspending value

    if deprecated:
        with pytest.warns(UserWarning):
            suspender = klass(signal, *sc_args, sleep=wait_time, is_async=True)
    else:
        suspender = klass(signal, *sc_args, sleep=wait_time, is_async=True)

    async def _set_after_time(delay, value):
        await asyncio.sleep(delay)
        await signal.set(value)

    tasks = []

    RE.install_suspender(suspender)
    if not task_in_plan:
        tasks.append(asyncio.create_task(_set_after_time(fail_time, fail_val)))
        tasks.append(asyncio.create_task(_set_after_time(resume_time, resume_val)))

    def _plan():
        if task_in_plan:
            tasks.append(asyncio.create_task(_set_after_time(fail_time, fail_val)))
            tasks.append(asyncio.create_task(_set_after_time(resume_time, resume_val)))
        yield from bps.checkpoint()
        yield from bps.sleep(sleep_time)

    start = time.time()
    RE(_plan())
    stop = time.time()
    for task in tasks:
        await task
    delta = stop - start
    assert delta >= resume_time + sleep_time + wait_time
