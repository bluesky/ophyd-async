from unittest.mock import patch

import pytest

from ophyd_async.core import DeviceCollector
from ophyd_async.epics.adcore import ADBase, ImageMode
from ophyd_async.epics.adsim import SimController


@pytest.fixture
async def ad(RE) -> SimController:
    async with DeviceCollector(mock=True):
        drv = ADBase("DRIVER:")
        controller = SimController(drv)

    return controller


async def test_ad_controller(RE, ad: SimController):
    with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
        await ad.arm(num=1)

    driver = ad.driver
    assert await driver.num_images.get_value() == 1
    assert await driver.image_mode.get_value() == ImageMode.multiple
    assert await driver.acquire.get_value() is True

    with patch("ophyd_async.epics.utils.wait_for_value", return_value=None):
        await ad.disarm()

    assert await driver.acquire.get_value() is False
