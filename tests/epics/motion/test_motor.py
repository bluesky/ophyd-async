import asyncio
import time
from typing import Dict
from unittest.mock import Mock, call

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    DeviceCollector,
    set_mock_put_proceeds,
    set_mock_value,
)
from ophyd_async.core.mock_signal_utils import callback_on_mock_put
from ophyd_async.epics.motion import motor

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_BIT = 0.001


@pytest.fixture
async def sim_motor():
    async with DeviceCollector(mock=True):
        sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X", name="sim_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.velocity, 1)
    yield sim_motor


async def wait_for_eq(item, attribute, comparison, timeout):
    timeout_time = time.monotonic() + timeout
    while getattr(item, attribute) != comparison:
        await asyncio.sleep(A_BIT)
        if time.monotonic() > timeout_time:
            raise TimeoutError


async def test_motor_moving_well(sim_motor: motor.Motor) -> None:
    set_mock_put_proceeds(sim_motor.user_setpoint, False)
    s = sim_motor.set(0.55)
    watcher = Mock()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await wait_for_eq(watcher, "call_count", 1, 1)
    assert watcher.call_args == call(
        name="sim_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )
    watcher.reset_mock()
    assert 0.55 == await sim_motor.user_setpoint.get_value()
    assert not s.done
    await asyncio.sleep(0.1)
    set_mock_value(sim_motor.user_readback, 0.1)
    await wait_for_eq(watcher, "call_count", 1, 1)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="sim_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_mock_value(sim_motor.motor_done_move, True)
    set_mock_value(sim_motor.user_readback, 0.55)
    set_mock_put_proceeds(sim_motor.user_setpoint, True)
    await asyncio.sleep(A_BIT)
    await wait_for_eq(s, "done", True, 1)
    done.assert_called_once_with(s)


async def test_motor_moving_well_2(sim_motor: motor.Motor) -> None:
    set_mock_put_proceeds(sim_motor.user_setpoint, False)
    s = sim_motor.set(0.55)
    watcher = Mock()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await asyncio.sleep(A_BIT)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="sim_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )
    watcher.reset_mock()
    assert 0.55 == await sim_motor.user_setpoint.get_value()
    assert not s.done
    await asyncio.sleep(0.1)
    set_mock_value(sim_motor.user_readback, 0.1)
    await asyncio.sleep(0.1)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="sim_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_mock_put_proceeds(sim_motor.user_setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    done.assert_called_once_with(s)


async def test_motor_move_timeout(sim_motor: motor.Motor):
    class MyTimeout(Exception):
        pass

    def do_timeout(value, wait=False, timeout=None):
        # Check we were given the right timeout of move_time + DEFAULT_TIMEOUT
        assert timeout == 10.3
        # Raise custom exception to be clear it bubbles up
        raise MyTimeout()

    callback_on_mock_put(sim_motor.user_setpoint, do_timeout)
    s = sim_motor.set(0.3)
    watcher = Mock()
    s.watch(watcher)
    with pytest.raises(MyTimeout):
        await s
    watcher.assert_called_once_with(
        name="sim_motor",
        current=0.0,
        initial=0.0,
        target=0.3,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )


async def test_motor_moving_stopped(sim_motor: motor.Motor):
    set_mock_value(sim_motor.motor_done_move, False)
    set_mock_put_proceeds(sim_motor.user_setpoint, False)
    s = sim_motor.set(1.5)
    s.add_callback(Mock())
    await asyncio.sleep(0.2)
    assert not s.done
    await sim_motor.stop()
    set_mock_put_proceeds(sim_motor.user_setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    assert s.success is False


async def test_read_motor(sim_motor: motor.Motor):
    await sim_motor.stage()
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.0
    assert (await sim_motor.read_configuration())["sim_motor-velocity"]["value"] == 1
    assert (await sim_motor.describe_configuration())["sim_motor-motor_egu"][
        "shape"
    ] == []
    set_mock_value(sim_motor.user_readback, 0.5)
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.5
    await sim_motor.unstage()
    # Check we can still read and describe when not staged
    set_mock_value(sim_motor.user_readback, 0.1)
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.1
    assert await sim_motor.describe()


async def test_set_velocity(sim_motor: motor.Motor) -> None:
    v = sim_motor.velocity
    q: asyncio.Queue[Dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["sim_motor-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["sim_motor-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["sim_motor-velocity"]["value"] == 3.0
    assert q.empty()
