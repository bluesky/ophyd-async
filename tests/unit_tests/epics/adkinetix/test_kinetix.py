from typing import cast

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adkinetix
from ophyd_async.testing import set_mock_value


@pytest.fixture
def test_adkinetix(ad_standard_det_factory) -> adkinetix.KinetixDetector:
    return ad_standard_det_factory(adkinetix.KinetixDetector)


async def test_get_deadtime(
    test_adkinetix: adkinetix.KinetixDetector,
):
    # Currently Kinetix driver doesn't support getting deadtime.
    assert test_adkinetix._controller.get_deadtime(0) == 0.001


async def test_trigger_modes(test_adkinetix: adkinetix.KinetixDetector):
    driver = cast(adkinetix.KinetixDriverIO, test_adkinetix.driver)
    set_mock_value(driver.trigger_mode, adkinetix.KinetixTriggerMode.INTERNAL)

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await test_adkinetix._controller.prepare(
            TriggerInfo(number_of_events=1, trigger=trig_mode)
        )
        await test_adkinetix._controller.arm()
        await test_adkinetix._controller.wait_for_idle()
        # Prevent timeouts
        set_mock_value(driver.acquire, True)

    # Default TriggerSource
    assert (await driver.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.EDGE_TRIGGER)
    assert (await driver.trigger_mode.get_value()) == "Rising Edge"

    await setup_trigger_mode(DetectorTrigger.CONSTANT_GATE)
    assert (await driver.trigger_mode.get_value()) == "Exp. Gate"

    await setup_trigger_mode(DetectorTrigger.INTERNAL)
    assert (await driver.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.VARIABLE_GATE)
    assert (await driver.trigger_mode.get_value()) == "Exp. Gate"
