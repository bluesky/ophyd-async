import asyncio
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    init_devices,
)
from ophyd_async.epics import adcore, adsimdetector
from ophyd_async.testing import get_mock_put, set_mock_value

TEST_DEADTIME = 0.1


@pytest.fixture
def driver(RE) -> adcore.ADBaseIO:
    with init_devices(mock=True):
        driver = adcore.ADBaseIO("DRV:", name="drv")
    return driver


@pytest.fixture
async def controller(RE, driver: adcore.ADBaseIO) -> adsimdetector.SimController:
    controller = adsimdetector.SimController(driver)
    controller.get_deadtime = lambda exposure: TEST_DEADTIME
    return controller


async def test_set_exposure_time_and_acquire_period_if_supplied_is_a_noop_if_no_exposure_supplied(  # noqa: E501
    controller: adsimdetector.SimController,
    driver: adcore.ADBaseIO,
):
    put_exposure = get_mock_put(driver.acquire_time)
    put_acquire_period = get_mock_put(driver.acquire_period)
    await controller.set_exposure_time_and_acquire_period_if_supplied(None)

    put_exposure.assert_not_called()
    put_acquire_period.assert_not_called()


@pytest.mark.parametrize(
    "exposure,expected_exposure,expected_acquire_period",
    [
        (0.0, 0.0, 0.1),
        (1.0, 1.0, 1.1),
        (1.5, 1.5, 1.6),
    ],
)
async def test_set_exposure_time_and_acquire_period_if_supplied_uses_deadtime(
    controller: adsimdetector.SimController,
    exposure: float,
    expected_exposure: float,
    expected_acquire_period: float,
):
    await controller.set_exposure_time_and_acquire_period_if_supplied(exposure)
    actual_exposure = await controller.driver.acquire_time.get_value()
    actual_acquire_period = await controller.driver.acquire_period.get_value()
    assert expected_exposure == actual_exposure
    assert expected_acquire_period == actual_acquire_period


@pytest.mark.timeout(18.0)
async def test_start_acquiring_driver_and_ensure_status_flags_immediate_failure(
    controller: adsimdetector.SimController,
):
    set_mock_value(controller.driver.detector_state, adcore.ADState.ERROR)
    acquiring = await controller.start_acquiring_driver_and_ensure_status()
    with pytest.raises(ValueError):
        await acquiring


async def test_start_acquiring_driver_and_ensure_status_fails_after_some_time(
    controller: adsimdetector.SimController,
):
    """This test ensures a failing status is captured halfway through acquisition.

    Real world application; it takes some time to start acquiring, and during that time
    the detector gets itself into a bad state.
    """
    set_mock_value(controller.driver.detector_state, adcore.ADState.IDLE)

    async def wait_then_fail():
        await asyncio.sleep(0)
        set_mock_value(controller.driver.detector_state, adcore.ADState.DISCONNECTED)

    await wait_then_fail()

    controller.frame_timeout = 0.1

    acquiring = await controller.start_acquiring_driver_and_ensure_status(
        start_timeout=0.2, state_timeout=0.2
    )

    with pytest.raises(
        ValueError, match="Final detector state Disconnected not in valid end states:"
    ):
        await acquiring


async def test_start_acquiring_driver_and_ensure_status_timing(
    controller: adsimdetector.SimController,
):
    """This test ensures the camera has time to return to a good state.

    Real world application; there is race condition wherein the
    detector has been asked to complete acquisition, but has not yet
    returned to a known good state before the status check.

    """
    set_mock_value(controller.driver.detector_state, adcore.ADState.ACQUIRE)

    acquiring = await controller.start_acquiring_driver_and_ensure_status(
        start_timeout=0.2, state_timeout=0.2
    )

    async def complete_acquire():
        """Return to idle state, but pretend the detector is slow."""
        await asyncio.sleep(0.05)
        set_mock_value(controller.driver.detector_state, adcore.ADState.IDLE)

    await asyncio.gather(acquiring, complete_acquire())


async def bad_observe_value(*args, **kwargs):
    "Stub to simulate a disconnected ``observe_value()``."
    if True:
        raise asyncio.TimeoutError()
    yield None  # Make it a generator


@patch("ophyd_async.epics.adcore._core_logic.observe_value", bad_observe_value)
async def test_start_acquiring_driver_and_ensure_status_disconnected(
    controller: adsimdetector.SimController,
):
    """This test ensures the function behaves gracefully if no detector
    states are available.

    """
    acquiring = await controller.start_acquiring_driver_and_ensure_status(
        start_timeout=0.2, state_timeout=0.2
    )

    with pytest.raises(asyncio.TimeoutError) as exc:
        await acquiring
    assert (
        str(exc.value)
        == "Could not monitor detector state: mock+ca://DRV:DetectorState_RBV"
    )
