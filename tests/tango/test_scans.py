from unittest.mock import Mock

import numpy as np
import pytest
from bluesky import RunEngine
from bluesky.plans import scan

from ophyd_async.core import DeviceCollector
from ophyd_async.tango.device_controllers import (
    DGG2Timer,
    OmsVME58Motor,
    SIS3820Counter,
)
from tango.asyncio_executor import set_global_executor

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_BIT = 0.001


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
@pytest.fixture
async def devices_set():
    async with DeviceCollector():
        omsvme58_motor = await OmsVME58Motor("p09/motor/eh.01")
        dgg2timer = await DGG2Timer("p09/dgg2/eh.01")
        sis3820 = await SIS3820Counter("p09/counter/eh.01")

    yield [omsvme58_motor, dgg2timer, sis3820]


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_step_scan_motor_vs_counter_with_dgg2(devices_set):
    omsvme58_motor, dgg2timer, sis3820 = devices_set

    readouts = Mock()

    # now let's do some bluesky stuff
    RE = RunEngine()
    RE(
        scan([omsvme58_motor, sis3820, dgg2timer], omsvme58_motor, 0, 1, num=11),
        readouts,
    )

    assert readouts.call_count == 14
    assert {arg[0][0] for arg in readouts.call_args_list} == {
        "descriptor",
        "event",
        "start",
        "stop",
    }

    positions = [
        args[0][1]["data"]["omsvme58_motor-position"]
        for args in readouts.call_args_list
        if args[0][0] == "event"
    ]
    for got, expected in zip(positions, np.arange(0, 1.1, 0.1)):
        assert pytest.approx(got, abs=0.1) == expected
