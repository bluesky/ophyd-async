import asyncio
from unittest.mock import Mock

import pytest

from ophyd_async.core import (
    DetectorController,
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
async def controller(RE, driver: adcore.ADBaseIO) -> Mock:
    controller = Mock(spec=DetectorController)
    controller.get_deadtime.return_value = TEST_DEADTIME
    return controller


async def test_set_exposure_time_and_acquire_period_if_supplied_is_a_noop_if_no_exposure_supplied(  # noqa: E501
    controller: DetectorController,
    driver: adcore.ADBaseIO,
):
    put_exposure = get_mock_put(driver.acquire_time)
    put_acquire_period = get_mock_put(driver.acquire_period)
    await adcore.set_exposure_time_and_acquire_period_if_supplied(
        controller, driver, None
    )
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
    controller: DetectorController,
    driver: adcore.ADBaseIO,
    exposure: float,
    expected_exposure: float,
    expected_acquire_period: float,
):
    await adcore.set_exposure_time_and_acquire_period_if_supplied(
        controller, driver, exposure
    )
    actual_exposure = await driver.acquire_time.get_value()
    actual_acquire_period = await driver.acquire_period.get_value()
    assert expected_exposure == actual_exposure
    assert expected_acquire_period == actual_acquire_period


async def test_start_acquiring_driver_and_ensure_status_flags_immediate_failure(
    driver: adcore.ADBaseIO,
):
    set_mock_value(driver.detector_state, adcore.DetectorState.Error)
    acquiring = await adcore.start_acquiring_driver_and_ensure_status(
        driver, timeout=0.01
    )
    with pytest.raises(ValueError):
        await acquiring


async def test_start_acquiring_driver_and_ensure_status_fails_after_some_time(
    driver: adcore.ADBaseIO,
):
    """This test ensures a failing status is captured halfway through acquisition.

    Real world application; it takes some time to start acquiring, and during that time
    the detector gets itself into a bad state.
    """
    set_mock_value(driver.detector_state, adcore.DetectorState.Idle)

    async def wait_then_fail():
        await asyncio.sleep(0)
        set_mock_value(driver.detector_state, adcore.DetectorState.Disconnected)

    acquiring = await adcore.start_acquiring_driver_and_ensure_status(
        driver, timeout=0.1
    )
    await wait_then_fail()

    with pytest.raises(ValueError):
        await acquiring
