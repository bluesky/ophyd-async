import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, set_mock_value
from ophyd_async.epics import adpilatus
from ophyd_async.epics.adcore import ImageMode


@pytest.fixture
async def mock_pilatus_driver(RE) -> adpilatus.PilatusDriverIO:
    async with DeviceCollector(mock=True):
        drv = adpilatus.PilatusDriverIO("DRIVER:")

    return drv


@pytest.fixture
async def mock_pilatus_controller(RE, pilatus_driver: adpilatus.PilatusDriverIO) -> adpilatus.PilatusController:
    async with DeviceCollector(mock=True):
        controller = adpilatus.PilatusController(pilatus_driver, readout_time=2.28)

    return controller


async def test_pilatus_controller(
    RE,
    mock_pilatus_controller: adpilatus.PilatusController,
    mock_pilatus_driver: adpilatus.PilatusDriverIO,
):
    set_mock_value(mock_pilatus_driver.armed_for_triggers, True)
    status = await mock_pilatus_controller.arm(num=1, trigger=DetectorTrigger.constant_gate)
    await status

    assert await mock_pilatus_driver.num_images.get_value() == 1
    assert await mock_pilatus_driver.image_mode.get_value() == ImageMode.multiple
    assert (
        await mock_pilatus_driver.trigger_mode.get_value() == adpilatus.PilatusTriggerMode.ext_enable
    )
    assert await mock_pilatus_driver.acquire.get_value() is True

    await mock_pilatus_controller.disarm()

    assert await mock_pilatus_driver.acquire.get_value() is False
