import pytest

from tango.asyncio_executor import set_global_executor

from ophyd_async.tango.sardana import SardanaMotor
from ophyd_async.core import DeviceCollector


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect():

    async with DeviceCollector():
        dummy_motor = await SardanaMotor("motor/dummy_mot_ctrl/1")

    assert dummy_motor.name == "dummy_motor"
