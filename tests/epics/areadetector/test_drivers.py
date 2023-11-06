# want to make a driver and test the following:
"""
1. If detector state is immediately in error, that this raises.
2. If after some time, the detector state is in error, this raises.
3. If no error happens but driver.acquire isn't being set in the timeout
"""
import asyncio

import pytest

from ophyd_async.core import DeviceCollector, set_sim_value
from ophyd_async.epics.areadetector.drivers import (
    ADBase,
    DetectorState,
    start_acquiring_driver_and_ensure_status,
)


@pytest.fixture
def driver(RE) -> ADBase:
    with DeviceCollector(sim=True):
        driver = ADBase("DRV:", name="drv")
    return driver


async def test_start_acquiring_driver_and_ensure_status_flags_immediate_failure(
    driver: ADBase,
):
    set_sim_value(driver.detector_state, DetectorState.Error)
    acquiring = await start_acquiring_driver_and_ensure_status(driver, timeout=0.01)
    with pytest.raises(
        ValueError,
        match="Final detector state Error not in valid end states: "
        + "{<DetectorState.Idle: 'Idle'>}",
    ):
        await acquiring


async def test_start_acquiring_driver_and_ensure_status_fails_after_some_time(
    driver: ADBase,
):
    """This test ensures a failing status is captured halfway through acquisition.

    Real world application; it takes some time to start acquiring, and during that time
    the detector gets itself into a bad state.
    """
    set_sim_value(driver.detector_state, DetectorState.Idle)

    async def wait_then_fail():
        await asyncio.sleep(0)
        set_sim_value(driver.detector_state, DetectorState.Disconnected)

    acquiring = await start_acquiring_driver_and_ensure_status(driver, timeout=0.1)
    await wait_then_fail()

    with pytest.raises(
        ValueError,
        match="Final detector state Disconnected not in valid end states: "
        + "{<DetectorState.Idle: 'Idle'>}",
    ):
        await acquiring
