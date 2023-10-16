from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector
from ophyd_async.core.flyer import SameTriggerDetectorGroupLogic, TriggerInfo
from ophyd_async.epics.areadetector.controllers import ADController, PilatusController
from ophyd_async.epics.areadetector.drivers import ADDriver, PilatusDriver, TriggerMode
from ophyd_async.epics.areadetector.utils import ImageMode


@pytest.fixture
async def pilatus(RE) -> PilatusController:
    async with DeviceCollector(sim=True):
        drv = PilatusDriver("DRIVER:")
        controller = PilatusController(drv)

    return controller


@pytest.fixture
async def ad(RE) -> ADController:
    async with DeviceCollector(sim=True):
        drv = ADDriver("DRIVER:")
        controller = ADController(drv)

    return controller


async def test_ad_controller(RE, ad: ADController):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await ad.arm()

    driver = ad.driver
    assert await driver.num_images.get_value() == 0
    assert await driver.image_mode.get_value() == ImageMode.single
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.controllers.ad_controller.wait_for_value",
        return_value=None,
    ):
        await ad.disarm()

    assert await driver.acquire.get_value() is False


async def test_pilatus_controller(RE, pilatus: PilatusController):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await pilatus.arm(mode=DetectorTrigger.constant_gate)

    driver = pilatus.driver
    assert await driver.num_images.get_value() == 0
    assert await driver.image_mode.get_value() == ImageMode.multiple
    assert await driver.trigger_mode.get_value() == TriggerMode.ext_enable
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.controllers.ad_controller.wait_for_value",
        return_value=None,
    ):
        await pilatus.disarm()

    assert await driver.acquire.get_value() is False


async def test_arming_pilatus_for_detector_group(
    RE, pilatus: PilatusController, ad: ADController
):
    detector_group = SameTriggerDetectorGroupLogic(
        controllers=[ad, pilatus], writers=[]
    )
    trigger_info = TriggerInfo(
        num=3, trigger=DetectorTrigger.constant_gate, deadtime=0.0015, livetime=0
    )

    with pytest.raises(AssertionError):
        await detector_group.ensure_armed(trigger_info)
