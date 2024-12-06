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
from ophyd_async.epics.core import (
    EpicsDevice,
    PvSuffix,
)
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
    "klass,sc_args,resume_val,fail_val,wait_time",
    [
        (SuspendBoolHigh, (), 0, 1, 0.2),
        (SuspendBoolLow, (), 1, 0, 0.2),
        (SuspendFloor, (0.5,), 1, 0, 0.2),
        (SuspendCeil, (0.5,), 0, 1, 0.2),
        (SuspendWhenOutsideBand, (0.5, 1.5), 1, 0, 0.2),
        ((SuspendInBand, True), (0.5, 1.5), 1, 0, 0.2),  # renamed to WhenOutsideBand
        ((SuspendOutBand, True), (0.5, 1.5), 0, 1, 0.2),
    ],
)


@PARAMETRIZE_SUSPENDERS
def test_suspender_installed_in_plan(
    klass, sc_args, resume_val, fail_val, wait_time, RE, suspend_device
):
    sleep_time = 0.2
    fail_time = 0.1
    resume_time = 0.5

    try:
        klass, deprecated = klass
    except TypeError:
        deprecated = False
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
    klass, sc_args, resume_val, fail_val, wait_time, RE, suspend_device
):
    sleep_time = 0.2
    fail_time = 0.1
    resume_time = 0.5

    await suspend_device.resume_signal.set(resume_val, wait=True)
    await suspend_device.fail_signal.set(fail_val, wait=True)
    await suspend_device.resume_time_signal.set(resume_time, wait=True)
    await suspend_device.fail_time_signal.set(fail_time, wait=True)
    await suspend_device.signal.set(resume_val, wait=True)

    try:
        klass, deprecated = klass
    except TypeError:
        deprecated = False
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
    await suspend_device.counter_signal.set(0, wait=True)
    start = time.time()
    RE(scan)
    stop = time.time()
    delta = stop - start
    assert delta >= resume_time + sleep_time + wait_time
