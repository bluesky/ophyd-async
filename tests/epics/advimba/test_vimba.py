from typing import cast

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adcore, advimba
from ophyd_async.epics.advimba import (
    VimbaExposeOutMode,
    VimbaOnOff,
    VimbaTriggerSource,
)
from ophyd_async.testing import set_mock_value


@pytest.fixture
def test_advimba(ad_standard_det_factory) -> advimba.VimbaDetector:
    return ad_standard_det_factory(advimba.VimbaDetector, adcore.ADHDFWriter)


async def test_get_deadtime(
    test_advimba: advimba.VimbaDetector,
):
    # Currently Vimba controller doesn't support getting deadtime.
    assert test_advimba._controller.get_deadtime(0) == 0.001


async def test_arming_trig_modes(test_advimba: advimba.VimbaDetector):
    driver = cast(advimba.VimbaDriverIO, test_advimba.driver)

    set_mock_value(driver.trigger_source, VimbaTriggerSource.FREERUN)
    set_mock_value(driver.trigger_mode, VimbaOnOff.OFF)
    set_mock_value(driver.exposure_mode, VimbaExposeOutMode.TIMED)

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await test_advimba._controller.prepare(
            TriggerInfo(number_of_events=1, trigger=trig_mode)
        )
        await test_advimba._controller.arm()
        await test_advimba._controller.wait_for_idle()
        # Prevent timeouts
        set_mock_value(driver.acquire, True)

    # Default TriggerSource
    assert (await driver.trigger_source.get_value()) == "Freerun"
    assert (await driver.trigger_mode.get_value()) == "Off"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.EDGE_TRIGGER)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.CONSTANT_GATE)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "TriggerWidth"

    await setup_trigger_mode(DetectorTrigger.INTERNAL)
    assert (await driver.trigger_source.get_value()) == "Freerun"
    assert (await driver.trigger_mode.get_value()) == "Off"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.VARIABLE_GATE)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "TriggerWidth"
