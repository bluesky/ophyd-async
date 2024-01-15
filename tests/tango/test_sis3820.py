import pytest

from unittest.mock import Mock

from tango.asyncio_executor import set_global_executor

from ophyd_async.tango.device_controllers import SIS3820Counter
from ophyd_async.core import DeviceCollector

from bluesky import RunEngine
from bluesky.plans import count


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
@pytest.fixture
async def sis3820():
    async with DeviceCollector():
        sis3820 = await SIS3820Counter("p09/counter/eh.01")

    yield sis3820


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect(sis3820):

    assert sis3820.name == "sis3820"


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_readout_with_bluesky(sis3820):

    readouts = Mock()
    # now let's do some bluesky stuff

    RE = RunEngine()
    RE(count([sis3820], 3), readouts)

    description = [args[0][1]['configuration'] for args in readouts.call_args_list if args[0][0] == "descriptor"][0]
    assert "sis3820" in description
    assert 'sis3820-offset' in description["sis3820"]["data"]

    readings = [args[0][1]['data'] for args in readouts.call_args_list if args[0][0] == "event"]
    assert len(readings) == 3
    assert "sis3820-counts" in readings[0]