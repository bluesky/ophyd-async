from unittest.mock import Mock

import pytest
from bluesky import Msg, RunEngine
from bluesky.plans import count
from tango.asyncio_executor import set_global_executor

from ophyd_async.core import DeviceCollector
from ophyd_async.tango.device_controllers import DGG2Timer


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
@pytest.fixture
async def dgg2():
    async with DeviceCollector():
        dgg2 = await DGG2Timer("p09/dgg2/eh.01")

    yield dgg2


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect(dgg2):

    assert dgg2.name == "dgg2"


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_readout_with_bluesky(dgg2):

    TEST_TIME = 0.1

    await dgg2.set_time(TEST_TIME)
    readouts = Mock()

    RE = RunEngine()

    RE([Msg("prepare", dgg2, TEST_TIME)])
    RE(count([dgg2], 3), readouts)

    description = [
        args[0][1]["configuration"]
        for args in readouts.call_args_list
        if args[0][0] == "descriptor"
    ][0]
    assert "dgg2" in description
    assert "dgg2-sampletime" in description["dgg2"]["data"]
    assert description["dgg2"]["data"]["dgg2-sampletime"] == pytest.approx(
        TEST_TIME, abs=0.1
    )

    readings = [
        args[0][1]["data"] for args in readouts.call_args_list if args[0][0] == "event"
    ]
    assert len(readings) == 3
    assert "dgg2-sampletime" in readings[0]
    assert readings[0]["dgg2-sampletime"] == pytest.approx(TEST_TIME, abs=0.1)
