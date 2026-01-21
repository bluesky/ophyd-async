import re
from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    EnableDisable,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def cont_acq_detector() -> adcore.AreaDetector[adcore.ADBaseIO]:
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    cb_plugin = adcore.NDCircularBuffIO("PREFIX:CB1:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(
            driver=driver, writer_type=None, plugins={"cb1": cb_plugin}
        )
        det.add_logics(
            adcore.ADContAcqArmLogic(driver, cb_plugin),
            adcore.ADContAcqTriggerLogic(driver, cb_plugin),
        )

    set_mock_value(
        driver.image_mode,
        adcore.ADImageMode.CONTINUOUS,
    )
    set_mock_value(driver.acquire_time, 0.8)
    set_mock_value(driver.acquire_period, 1.0)
    set_mock_value(driver.acquire, True)
    return det


async def test_cont_acq_controller_invalid_trigger_mode(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    trigger_info = TriggerInfo(trigger=DetectorTrigger.EXTERNAL_EDGE)
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Trigger type DetectorTrigger.EXTERNAL_EDGE not supported by 'det', "
            "supported types are: [INTERNAL]"
        ),
    ):
        await cont_acq_detector.prepare(trigger_info)


ERROR_MESSAGE = (
    "Driver must be acquiring in continuous mode to use the cont acq interface"
)


async def test_cont_acq_controller_not_in_continuous_mode(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    set_mock_value(cont_acq_detector.driver.image_mode, adcore.ADImageMode.SINGLE)
    with pytest.raises(RuntimeError, match=ERROR_MESSAGE):
        await cont_acq_detector.trigger()


async def test_cont_acq_controller_not_acquiring(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    set_mock_value(cont_acq_detector.driver.acquire, False)
    with pytest.raises(RuntimeError, match=ERROR_MESSAGE):
        await cont_acq_detector.trigger()


async def test_cont_acq_controller_invalid_exposure_time(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Detector exposure time currently set to 0.8, but requested exposure is 1.0"
        ),
    ):
        await cont_acq_detector.prepare(TriggerInfo(livetime=1.0))


async def test_cont_acq_controller_success(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    await cont_acq_detector.stage()
    await cont_acq_detector.trigger()
    assert_has_calls(
        cont_acq_detector,
        [
            call.cb1.capture.put(False, wait=False),
            call.cb1.enable_callbacks.put(EnableDisable.ENABLE, wait=True),
            call.cb1.pre_count.put(0, wait=True),
            call.cb1.post_count.put(1, wait=True),
            call.cb1.preset_trigger_count.put(1, wait=True),
            call.cb1.flush_on_soft_trg.put(
                adcore.NDCBFlushOnSoftTrgMode.ON_NEW_IMAGE, wait=True
            ),
            call.cb1.capture.put(True, wait=True),
        ],
    )
