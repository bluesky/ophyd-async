import pytest
import asyncio

import numpy as np

from unittest.mock import Mock, call

from tango.asyncio_executor import set_global_executor

from ophyd_async.tango.sardana import SardanaMotor
from ophyd_async.tango.device_controllers import OmsVME58Motor
from ophyd_async.core import DeviceCollector

from bluesky import RunEngine
from bluesky.plans import count, scan
from bluesky.plan_stubs import mv


# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_BIT = 0.001

# dict: {class: tango trl}
MOTORS_TO_TEST = {
    SardanaMotor: "motor/dummy_mot_ctrl/1",
    OmsVME58Motor: "p09/motor/eh.01"
}


# --------------------------------------------------------------------
@pytest.fixture(
    params=list(MOTORS_TO_TEST.items()),
    ids=list(MOTORS_TO_TEST.keys()),
)
def motor_to_test(request):
    return request.param


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
@pytest.fixture
async def dummy_motor(motor_to_test):
    async with DeviceCollector():
        dummy_motor = await motor_to_test[0](motor_to_test[1])

    yield dummy_motor


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect(dummy_motor):

    assert dummy_motor.name == "dummy_motor"


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_readout_with_bluesky(dummy_motor):

    # now let's do some bluesky stuff
    RE = RunEngine()
    RE(count([dummy_motor], 1))


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_move(dummy_motor):
    start_position = await dummy_motor.position.get_value()
    target_position = start_position + 1

    status = dummy_motor.set(target_position)
    watcher = Mock()
    status.watch(watcher)
    done = Mock()
    status.add_callback(done)
    await asyncio.sleep(A_BIT)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="dummy_motor",
        current=start_position,
        initial=start_position,
        target=target_position,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )
    await status
    assert pytest.approx(target_position, abs=0.1) == await dummy_motor.position.get_value()
    assert status.done
    done.assert_called_once_with(status)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_move_with_bluesky(dummy_motor):
    start_position = await dummy_motor.position.get_value()
    target_position = start_position + 1

    # now let's do some bluesky stuff
    RE = RunEngine()
    RE(mv(dummy_motor, target_position))


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_motor_vs_motor_position(dummy_motor):

    readouts = Mock()

    # now let's do some bluesky stuff
    RE = RunEngine()
    RE(scan([dummy_motor.position], dummy_motor, 0, 1, num=11), readouts)

    assert readouts.call_count == 14
    assert set([args[0][0] for args in readouts.call_args_list]) == {'descriptor', 'event', 'start', 'stop'}

    positions = [args[0][1]['data']['dummy_motor-position'] for args in readouts.call_args_list if args[0][0] == "event"]
    for got, expected in zip(positions, np.arange(0, 1.1, 0.1)):
        assert pytest.approx(got, abs=0.1) == expected