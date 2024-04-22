from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector
from ophyd_async.epics.areadetector.controllers import (
    ADSimController,
    PilatusController,
)
from ophyd_async.epics.areadetector.drivers import ADBase, PilatusDriver
from ophyd_async.epics.areadetector.drivers.pilatus_driver import PilatusTriggerMode
from ophyd_async.epics.areadetector.utils import ImageMode


@pytest.fixture
async def pilatus(RE) -> PilatusController:
    async with DeviceCollector(sim=True):
        drv = PilatusDriver("DRIVER:")
        controller = PilatusController(drv)

    return controller


@pytest.fixture
async def ad(RE) -> ADSimController:
    async with DeviceCollector(sim=True):
        drv = ADBase("DRIVER:")
        controller = ADSimController(drv)

    return controller


async def test_ad_controller(RE, ad: ADSimController):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await ad.arm(num=1)

    driver = ad.driver
    assert await driver.num_images.get_value() == 1
    assert await driver.image_mode.get_value() == ImageMode.multiple
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.utils.wait_for_value", return_value=None
    ):
        await ad.disarm()

    assert await driver.acquire.get_value() is False


async def test_pilatus_controller(RE, pilatus: PilatusController):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await pilatus.arm(num=1, trigger=DetectorTrigger.constant_gate)

    driver = pilatus._drv
    assert await driver.num_images.get_value() == 1
    assert await driver.image_mode.get_value() == ImageMode.multiple
    assert await driver.trigger_mode.get_value() == PilatusTriggerMode.ext_enable
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.areadetector.utils.wait_for_value", return_value=None
    ):
        await pilatus.disarm()

    assert await driver.acquire.get_value() is False
