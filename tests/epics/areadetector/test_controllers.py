from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, set_mock_value
from ophyd_async.epics.areadetector.controllers import (
    ADSimController,
    PilatusController,
)
from ophyd_async.epics.areadetector.drivers import ADBase, PilatusDriver
from ophyd_async.epics.areadetector.drivers.pilatus_driver import PilatusTriggerMode
from ophyd_async.epics.areadetector.utils import ImageMode


@pytest.fixture
async def pilatus_driver(RE) -> PilatusDriver:
    async with DeviceCollector(mock=True):
        drv = PilatusDriver("DRIVER:")

    return drv


@pytest.fixture
async def pilatus(RE, pilatus_driver: PilatusDriver) -> PilatusController:
    async with DeviceCollector(mock=True):
        controller = PilatusController(pilatus_driver)

    return controller


@pytest.fixture
async def ad(RE) -> ADSimController:
    async with DeviceCollector(mock=True):
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


async def test_pilatus_controller(
    RE,
    pilatus: PilatusController,
    pilatus_driver: PilatusDriver,
):
    set_mock_value(pilatus_driver.armed_for_triggers, True)
    status = await pilatus.arm(num=1, trigger=DetectorTrigger.constant_gate)
    await status

    assert await pilatus_driver.num_images.get_value() == 1
    assert await pilatus_driver.image_mode.get_value() == ImageMode.multiple
    assert (
        await pilatus_driver.trigger_mode.get_value() == PilatusTriggerMode.ext_enable
    )
    assert await pilatus_driver.acquire.get_value() is True

    await pilatus.disarm()

    assert await pilatus_driver.acquire.get_value() is False
