import pytest

from ophyd_async.core import DetectorTrigger, TriggerInfo, init_devices
from ophyd_async.epics import adcore
from ophyd_async.testing import set_mock_value


@pytest.fixture
def cont_acq_det(ad_standard_det_factory):
    det = ad_standard_det_factory(adcore.ContAcqAreaDetector)

    # Set a few additional settings specific to cont acq detectors
    set_mock_value(det.driver.acquire, True)
    set_mock_value(det.cb_plugin.array_size_x, 10)
    set_mock_value(det.cb_plugin.array_size_y, 10)

    return det


@pytest.fixture
def cont_acq_controller(RE):
    with init_devices(mock=True):
        drv = adcore.ADBaseIO("DRV")
        cb_plugin = adcore.NDPluginCBIO("CB1")

    set_mock_value(drv.image_mode, adcore.ADImageMode.CONTINUOUS)
    set_mock_value(drv.acquire_time, 0.8)
    set_mock_value(drv.acquire_period, 1.0)
    set_mock_value(drv.acquire, True)
    return adcore.ADBaseContAcqController(drv, cb_plugin)


@pytest.fixture
def one_shot_trigger_info_factory():
    def generate_one_shot_trigger_info(
        trigger_mode=DetectorTrigger.INTERNAL, livetime=0.8
    ):
        if trigger_mode != DetectorTrigger.INTERNAL:
            return TriggerInfo(
                number_of_triggers=1,
                trigger=trigger_mode,
                livetime=livetime,
                deadtime=0.001,
            )
        else:
            return TriggerInfo(
                number_of_triggers=1, trigger=trigger_mode, livetime=livetime
            )

    return generate_one_shot_trigger_info


async def test_cont_acq_controller_invalid_trigger_mode(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    trigger_info = one_shot_trigger_info_factory(
        trigger_mode=DetectorTrigger.CONSTANT_GATE
    )
    with pytest.raises(TypeError) as e:
        await cont_acq_controller.prepare(trigger_info)
    assert (
        str(e.value)
        == "The continuous acq interface only supports internal triggering."
    )


async def test_cont_acq_controller_invalid_exp_time(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    with pytest.raises(ValueError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory(livetime=0.1))
    assert (
        str(e.value)
        == "Detector exposure time currently set to 0.8, but requested exposure is 0.1"
    )


async def test_cont_acq_controller_not_in_continuous_mode(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    set_mock_value(cont_acq_controller.driver.image_mode, adcore.ADImageMode.SINGLE)

    with pytest.raises(RuntimeError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory())
    assert (
        str(e.value)
        == "Driver must be acquiring in continuous mode to use the cont acq interface"
    )


async def test_cont_acq_controller_not_acquiring(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    set_mock_value(cont_acq_controller.driver.acquire, False)

    with pytest.raises(RuntimeError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory())
    assert (
        str(e.value)
        == "Driver must be acquiring in continuous mode to use the cont acq interface"
    )
