import asyncio

import pytest

from ophyd_async.core import (
    DeviceCollector,
    get_mock_put,
    set_mock_value,
)
from ophyd_async.epics import adcore

TEST_DEADTIME = 0.1


@pytest.fixture
def driver(RE) -> adcore.ADBaseIO:
    with DeviceCollector(mock=True):
        driver = adcore.ADBaseIO("DRV:", name="drv")
    return driver


@pytest.fixture
async def controller(RE, driver: adcore.ADBaseIO) -> adcore.ADBaseController:
    controller = adcore.ADBaseController(driver)
    controller.get_deadtime = lambda exposure: TEST_DEADTIME
    return controller


async def test_set_exposure_time_and_acquire_period_if_supplied_is_a_noop_if_no_exposure_supplied(  # noqa: E501
    controller: adcore.ADBaseController,
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
    controller: adcore.ADBaseController,
    exposure: float,
    expected_exposure: float,
    expected_acquire_period: float,
):
    await controller.set_exposure_time_and_acquire_period_if_supplied(exposure)
    actual_exposure = await controller._driver.acquire_time.get_value()
    actual_acquire_period = await controller._driver.acquire_period.get_value()
    assert expected_exposure == actual_exposure
    assert expected_acquire_period == actual_acquire_period


async def test_start_acquiring_driver_and_ensure_status_flags_immediate_failure(
    controller: adcore.ADBaseController,
):
    set_mock_value(controller._driver.detector_state, adcore.DetectorState.Error)
    acquiring = await controller.start_acquiring_driver_and_ensure_status()
    with pytest.raises(ValueError):
        await acquiring


async def test_start_acquiring_driver_and_ensure_status_fails_after_some_time(
    controller: adcore.ADBaseController,
):
    """This test ensures a failing status is captured halfway through acquisition.

    Real world application; it takes some time to start acquiring, and during that time
    the detector gets itself into a bad state.
    """
    set_mock_value(controller._driver.detector_state, adcore.DetectorState.Idle)

    async def wait_then_fail():
        await asyncio.sleep(0)
        set_mock_value(
            controller._driver.detector_state, adcore.DetectorState.Disconnected
        )

    controller.frame_timeout = 0.1

    acquiring = await controller.start_acquiring_driver_and_ensure_status()
    await wait_then_fail()

    with pytest.raises(ValueError):
        await acquiring
