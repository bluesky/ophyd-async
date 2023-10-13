from unittest.mock import patch

from ophyd_async.core import DetectorTrigger, DeviceCollector
from ophyd_async.epics.areadetector.controllers import ADController, PilatusController
from ophyd_async.epics.areadetector.drivers import ADDriver, PilatusDriver, TriggerMode
from ophyd_async.epics.areadetector.utils import ImageMode


async def test_standard_controller(RE):
    with DeviceCollector(sim=True):
        drv = ADDriver("DRIVER:")
        controller = ADController(drv)

    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await controller.arm()

    driver = controller.driver
    assert await driver.num_images.get_value() == 0
    assert await driver.image_mode.get_value() == ImageMode.single
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.controllers.ad_controller.wait_for_value",
        return_value=None,
    ):
        await controller.disarm()

    assert await driver.acquire.get_value() is False


async def test_pilatus_controller(RE):
    with DeviceCollector(sim=True):
        drv = PilatusDriver("DRIVER:")
        controller = PilatusController(drv)

    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await controller.arm(mode=DetectorTrigger.constant_gate)

    assert await drv.num_images.get_value() == 0
    assert await drv.image_mode.get_value() == ImageMode.multiple
    assert await drv.trigger_mode.get_value() == TriggerMode.ext_enable
    assert await drv.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.controllers.ad_controller.wait_for_value",
        return_value=None,
    ):
        await controller.disarm()

    assert await drv.acquire.get_value() is False
