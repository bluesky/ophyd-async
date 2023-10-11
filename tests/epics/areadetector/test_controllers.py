from ophyd_async.epics.areadetector.controllers import StandardController
from unittest.mock import AsyncMock, MagicMock, patch
from ophyd_async.epics.areadetector.drivers.ad_driver import ADDriver
from ophyd_async.core import DeviceCollector, DEFAULT_TIMEOUT

from ophyd_async.epics.areadetector.utils import ImageMode


async def test_standard_controller(RE):
    with DeviceCollector(sim=True):
        driver = ADDriver("DRIVER:")

    controller = StandardController(driver)


    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await controller.arm()

    assert await driver.num_images.get_value() == 0
    assert await driver.image_mode.get_value() == ImageMode.single
    assert await driver.acquire.get_value() == True
    
    with patch("ophyd_async.epics.areadetector.controllers.standard_controller.wait_for_value", return_value=None):
        await controller.disarm()

    assert await driver.acquire.get_value() == False
