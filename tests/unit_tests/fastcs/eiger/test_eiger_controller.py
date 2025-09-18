from unittest.mock import ANY, call

from pytest import fixture

from ophyd_async.core import (
    TriggerInfo,
    init_devices,
)
from ophyd_async.fastcs.eiger import EigerController, EigerDriverIO
from ophyd_async.testing import (
    callback_on_mock_put,
    get_mock,
    get_mock_put,
    set_mock_value,
)

DriverAndController = tuple[EigerDriverIO, EigerController]


@fixture
def eiger_driver_and_controller_no_arm(RE) -> DriverAndController:
    with init_devices(mock=True):
        driver = EigerDriverIO("")
        controller = EigerController(driver)

    def become_idle_after_arm(*args, **kwargs):
        # Mocking that eiger has armed and finished taking frames.
        set_mock_value(driver.detector.state, "idle")

    callback_on_mock_put(driver.detector.arm, become_idle_after_arm)

    return driver, controller


@fixture
def eiger_driver_and_controller(
    eiger_driver_and_controller_no_arm: DriverAndController,
) -> DriverAndController:
    driver, controller = eiger_driver_and_controller_no_arm

    return driver, controller


async def test_when_arm_with_exposure_then_time_and_period_set(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    test_exposure = 0.002
    await controller.prepare(TriggerInfo(number_of_events=10, livetime=test_exposure))
    await controller.arm()
    await controller.wait_for_idle()
    assert (await driver.detector.frame_time.get_value()) == test_exposure
    assert (await driver.detector.count_time.get_value()) == test_exposure


async def test_when_arm_with_no_exposure_then_arm_set_correctly(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    await controller.prepare(TriggerInfo(number_of_events=10))
    await controller.arm()
    await controller.wait_for_idle()
    get_mock_put(driver.detector.arm).assert_called_once()


async def test_when_arm_with_number_of_images_then_number_of_images_set_correctly(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    test_number_of_images = 40
    await controller.prepare(TriggerInfo(number_of_events=test_number_of_images))
    await controller.arm()
    await controller.wait_for_idle()
    get_mock_put(driver.detector.nimages).assert_called_once_with(
        test_number_of_images, wait=ANY
    )


async def test_when_disarm_called_on_controller_then_disarm_called_on_driver(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    await controller.disarm()
    get_mock_put(driver.detector.disarm).assert_called_once()


async def test_when_get_deadtime_called_then_returns_expected_deadtime(
    eiger_driver_and_controller: DriverAndController,
):
    _, controller = eiger_driver_and_controller
    assert controller.get_deadtime(0) == 0.0001


async def test_given_energy_within_tolerance_when_photon_energy_set_then_pv_unchanged(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    initial_energy = 10
    set_mock_value(driver.detector.photon_energy, initial_energy)
    await controller.set_energy(10.002)
    get_mock_put(driver.detector.photon_energy).assert_not_called()
    assert (await driver.detector.photon_energy.get_value()) == initial_energy


async def test_given_energy_outside_tolerance_when_photon_energy_set_then_pv_changed(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller
    initial_energy = 10
    new_energy = 15
    set_mock_value(driver.detector.photon_energy, initial_energy)
    await controller.set_energy(new_energy)
    get_mock_put(driver.detector.photon_energy).assert_called_once()
    assert (await driver.detector.photon_energy.get_value()) == new_energy


async def test_when_prepare_called__correct_parameters_set(
    eiger_driver_and_controller: DriverAndController,
):
    driver, controller = eiger_driver_and_controller

    await controller.prepare(TriggerInfo(livetime=1))

    detector_mock = get_mock(driver.detector)
    mock_calls = detector_mock.mock_calls
    assert [
        call.trigger_mode.put("ints", wait=True),
        call.nimages.put(1, wait=True),
        call.count_time.put(1.0, wait=True),
        call.frame_time.put(1.0, wait=True),
    ] in mock_calls
