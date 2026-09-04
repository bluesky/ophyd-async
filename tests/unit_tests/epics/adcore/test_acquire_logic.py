import asyncio
import re
from unittest.mock import call

import pytest

from ophyd_async.core import (
    callback_on_mock_put,
    init_devices,
    set_callback_filter,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def adbase_detector() -> adcore.AreaDetector[adcore.ADBaseIO]:
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(driver=driver)
        det.add_detector_logics(adcore.ADAcquireLogic(driver))
    return det


async def test_acquire_logic_trigger_internal_calls_acquire(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    await adbase_detector.trigger()
    assert_has_calls(
        adbase_detector.driver,
        [
            call.acquire.put(True),
        ],
    )


async def test_acquire_logic_when_arming_times_out():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(driver=driver)
        det.add_detector_logics(adcore.ADAcquireLogic(driver, timeout=0.02))

    async def sleep_for_a_bit(value):
        await asyncio.sleep(0.02)

    callback_on_mock_put(det.driver.acquire, sleep_for_a_bit)

    with pytest.raises(
        TimeoutError,
        match=re.escape(
            "det-driver-acquire didn't match True in 0.02s, last value False"
        ),
    ):
        await det.trigger()

    await asyncio.sleep(0.03)


async def test_acquire_logic_wait_for_idle_in_bad_state():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(driver=driver)
        det.add_detector_logics(adcore.ADAcquireLogic(driver, timeout=0.05))

    set_mock_value(driver.detector_state, adcore.ADState.ERROR)

    with pytest.raises(ValueError) as exc_info:
        await det.trigger()

    error_msg = str(exc_info.value)
    assert "DetectorState_RBV not in a good state: Error: expected" in error_msg
    assert "ADState.IDLE" in error_msg
    assert "ADState.ABORTED" in error_msg


async def test_start_acquiring_driver_and_ensure_status_timing(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    """This test ensures the camera has time to return to a good state.

    Real world application; there is race condition wherein the
    detector has been asked to complete acquisition, but has not yet
    returned to a known good state before the status check.

    """
    set_mock_value(
        adbase_detector.driver.detector_state,
        adcore.ADState.ACQUIRE,
    )

    async def complete_acquire() -> None:
        """Return to idle state, but pretend the detector is slow."""
        await asyncio.sleep(0.1)
        set_mock_value(
            adbase_detector.driver.detector_state,
            adcore.ADState.IDLE,
        )

    await asyncio.gather(adbase_detector.trigger(), complete_acquire())


async def test_acquire_logic_disarm(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    await adbase_detector.unstage()
    assert_has_calls(
        adbase_detector.driver,
        [
            call.acquire.put(False),
        ],
    )


async def test_start_acquiring_driver_and_ensure_status_disconnected():
    """This test ensures the function behaves gracefully if no detector
    states are available.

    """
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(driver=driver)
        det.add_detector_logics(adcore.ADAcquireLogic(driver, timeout=0.1))

    set_callback_filter(driver.detector_state, lambda v: None)

    with pytest.raises(asyncio.TimeoutError) as exc:
        await det.trigger()
    assert (
        str(exc.value)
        == "Could not monitor state: mock+ca://PREFIX:DRV:DetectorState_RBV"
    )
