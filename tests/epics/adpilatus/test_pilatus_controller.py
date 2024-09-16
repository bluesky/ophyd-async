import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, set_mock_value
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adcore, adpilatus


@pytest.fixture
async def pilatus_driver(RE) -> adpilatus.PilatusDriverIO:
    async with DeviceCollector(mock=True):
        drv = adpilatus.PilatusDriverIO("DRIVER:")

    return drv


@pytest.fixture
async def pilatus(
    RE, pilatus_driver: adpilatus.PilatusDriverIO
) -> adpilatus.PilatusController:
    async with DeviceCollector(mock=True):
        controller = adpilatus.PilatusController(pilatus_driver, readout_time=2.28)

    return controller


async def test_pilatus_controller(
    RE,
    pilatus: adpilatus.PilatusController,
    pilatus_driver: adpilatus.PilatusDriverIO,
):
    set_mock_value(pilatus_driver.armed, True)
    await pilatus.prepare(TriggerInfo(number=1, trigger=DetectorTrigger.constant_gate))
    await pilatus.arm()
    await pilatus.wait_for_idle()

    assert await pilatus_driver.num_images.get_value() == 1
    assert await pilatus_driver.image_mode.get_value() == adcore.ImageMode.multiple
    assert (
        await pilatus_driver.trigger_mode.get_value()
        == adpilatus.PilatusTriggerMode.ext_enable
    )
    assert await pilatus_driver.acquire.get_value() is True

    await pilatus.disarm()

    assert await pilatus_driver.acquire.get_value() is False
