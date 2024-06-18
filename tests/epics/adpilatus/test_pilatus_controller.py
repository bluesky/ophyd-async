import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, set_mock_value
from ophyd_async.epics import ImageMode
from ophyd_async.epics.adpilatus import (PilatusController, PilatusDriver,
                                         PilatusTriggerMode)


@pytest.fixture
async def pilatus_driver(RE) -> PilatusDriver:
    async with DeviceCollector(mock=True):
        drv = PilatusDriver("DRIVER:")

    return drv


@pytest.fixture
async def pilatus(RE, pilatus_driver: PilatusDriver) -> PilatusController:
    async with DeviceCollector(mock=True):
        controller = PilatusController(pilatus_driver, readout_time=2.28)

    return controller


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
