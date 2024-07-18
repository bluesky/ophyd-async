from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, set_mock_value
from ophyd_async.epics import adcore, adpilatus, adsimdetector


@pytest.fixture
async def pilatus_driver(RE) -> adpilatus.PilatusDriver:
    async with DeviceCollector(mock=True):
        drv = adpilatus.PilatusDriver("DRIVER:")

    return drv


@pytest.fixture
async def pilatus(RE, pilatus_driver: adpilatus.PilatusDriver) -> adpilatus.PilatusController:
    async with DeviceCollector(mock=True):
        controller = adpilatus.PilatusController(pilatus_driver, readout_time=2.28)

    return controller


@pytest.fixture
async def ad(RE) -> adsimdetector.ADSimController:
    async with DeviceCollector(mock=True):
        drv = adcore.ADBase("DRIVER:")
        controller = adsimdetector.ADSimController(drv)

    return controller


async def test_ad_controller(RE, ad: adsimdetector.ADSimController):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        await ad.arm(num=1)

    driver = ad.driver
    assert await driver.num_images.get_value() == 1
    assert await driver.image_mode.get_value() == adcore.ImageMode.multiple
    assert await driver.acquire.get_value() is True

    with patch(
        "ophyd_async.epics.adcore._utils.wait_for_value", return_value=None
    ):
        await ad.disarm()

    assert await driver.acquire.get_value() is False


async def test_pilatus_controller(
    RE,
    pilatus: adpilatus.PilatusController,
    pilatus_driver: adpilatus.PilatusDriver,
):
    set_mock_value(pilatus_driver.armed_for_triggers, True)
    status = await pilatus.arm(num=1, trigger=DetectorTrigger.constant_gate)
    await status

    assert await pilatus_driver.num_images.get_value() == 1
    assert await pilatus_driver.image_mode.get_value() == adcore.ImageMode.multiple
    assert (
        await pilatus_driver.trigger_mode.get_value() == adpilatus.PilatusTriggerMode.ext_enable
    )
    assert await pilatus_driver.acquire.get_value() is True

    await pilatus.disarm()

    assert await pilatus_driver.acquire.get_value() is False
