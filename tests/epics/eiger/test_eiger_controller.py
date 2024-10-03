from unittest.mock import ANY, patch

from pytest import fixture, raises

from ophyd_async.core import (
    DeviceCollector,
    callback_on_mock_put,
    get_mock_put,
    set_mock_value,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics.eiger._eiger_controller import EigerController
from ophyd_async.epics.eiger._eiger_io import EigerDriverIO

DriverAndController = tuple[EigerDriverIO, EigerController]


@fixture
def eiger_driver_and_controller_no_arm(RE) -> DriverAndController:
    with DeviceCollector(mock=True):
        driver = EigerDriverIO("")
        controller = EigerController(driver)

    return driver, controller


@fixture
def eiger_driver_and_controller(
    eiger_driver_and_controller_no_arm: DriverAndController,
) -> DriverAndController:
    driver, controller = eiger_driver_and_controller_no_arm

    def become_ready_on_arm(*args, **kwargs):
        if args[0] == 1:
            set_mock_value(driver.state, "ready")

    callback_on_mock_put(driver.arm, become_ready_on_arm)

    return driver, controller


async def test_when_arm_with_exposure_then_time_and_period_set(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    test_exposure = 0.002
    await controller.prepare(TriggerInfo(number_of_triggers=10, livetime=test_exposure))
    await controller.arm()
    await controller.wait_for_idle()
    assert (await driver.acquire_period.get_value()) == test_exposure
    assert (await driver.acquire_time.get_value()) == test_exposure


async def test_when_arm_with_no_exposure_then_arm_set_correctly(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    await controller.prepare(TriggerInfo(number_of_triggers=10))
    await controller.arm()
    await controller.wait_for_idle()
    get_mock_put(driver.arm).assert_called_once_with(1, wait=ANY, timeout=ANY)


async def test_when_arm_with_number_of_images_then_number_of_images_set_correctly(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    test_number_of_images = 40
    await controller.prepare(TriggerInfo(number_of_triggers=test_number_of_images))
    await controller.arm()
    await controller.wait_for_idle()
    get_mock_put(driver.num_images).assert_called_once_with(
        test_number_of_images, wait=ANY, timeout=ANY
    )


@patch("ophyd_async.epics.eiger._eiger_controller.DEFAULT_TIMEOUT", 0.1)
async def test_given_detector_fails_to_go_ready_when_arm_called_then_fails(
    eiger_driver_and_controller_no_arm: DriverAndController,
):
    driver, controller = eiger_driver_and_controller_no_arm
    with raises(TimeoutError):
        await controller.prepare(TriggerInfo(number_of_triggers=10))
        await controller.arm()
        await controller.wait_for_idle()


async def test_when_disarm_called_on_controller_then_disarm_called_on_driver(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    await controller.disarm()
    get_mock_put(driver.disarm).assert_called_once_with(1, wait=ANY, timeout=ANY)


async def test_when_get_deadtime_called_then_returns_expected_deadtime(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    assert controller.get_deadtime(0) == 0.0001


async def test_given_energy_within_tolerance_when_photon_energy_set_then_pv_unchanged(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    initial_energy = 10
    set_mock_value(driver.photon_energy, initial_energy)
    await controller.set_energy(10.002)
    get_mock_put(driver.photon_energy).assert_not_called()
    assert (await driver.photon_energy.get_value()) == initial_energy


async def test_given_energy_outside_tolerance_when_photon_energy_set_then_pv_changed(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    initial_energy = 10
    new_energy = 15
    set_mock_value(driver.photon_energy, initial_energy)
    await controller.set_energy(new_energy)
    get_mock_put(driver.photon_energy).assert_called_once()
    assert (await driver.photon_energy.get_value()) == new_energy
