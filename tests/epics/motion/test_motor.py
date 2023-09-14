import asyncio
from typing import Dict
from unittest.mock import Mock, call

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import DeviceCollector, set_sim_put_proceeds, set_sim_value
from ophyd_async.epics.motion import motor

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_BIT = 0.001


@pytest.fixture
async def sim_motor():
    async with DeviceCollector(sim=True):
        sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        # Signals connected here

    assert sim_motor.name == "sim_motor"
    set_sim_value(sim_motor.units, "mm")
    set_sim_value(sim_motor.precision, 3)
    set_sim_value(sim_motor.velocity, 1)
    yield sim_motor


async def test_motor_moving_well(sim_motor: motor.Motor) -> None:
    set_sim_put_proceeds(sim_motor.setpoint, False)
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
    assert 0.55 == await sim_motor.setpoint.get_value()
    assert not s.done
    await asyncio.sleep(0.1)
    set_sim_value(sim_motor.readback, 0.1)
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
    set_sim_put_proceeds(sim_motor.setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    done.assert_called_once_with(s)


async def test_motor_moving_stopped(sim_motor: motor.Motor):
    set_sim_put_proceeds(sim_motor.setpoint, False)
    s = sim_motor.set(1.5)
    s.add_callback(Mock())
    await asyncio.sleep(0.2)
    assert not s.done
    await sim_motor.stop()
    set_sim_put_proceeds(sim_motor.setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    assert s.success is False


async def test_read_motor(sim_motor: motor.Motor):
    sim_motor.stage()
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.0
    assert (await sim_motor.describe())["sim_motor"][
        "source"
    ] == "sim://BLxxI-MO-TABLE-01:X.RBV"
    assert (await sim_motor.read_configuration())["sim_motor-velocity"]["value"] == 1
    assert (await sim_motor.describe_configuration())["sim_motor-units"]["shape"] == []
    set_sim_value(sim_motor.readback, 0.5)
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.5
    sim_motor.unstage()
    # Check we can still read and describe when not staged
    set_sim_value(sim_motor.readback, 0.1)
    assert (await sim_motor.read())["sim_motor"]["value"] == 0.1
    assert await sim_motor.describe()


async def test_set_velocity(sim_motor: motor.Motor) -> None:
    v = sim_motor.velocity
    assert (await v.describe())["sim_motor-velocity"][
        "source"
    ] == "sim://BLxxI-MO-TABLE-01:X.VELO"
    q: asyncio.Queue[Dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["sim_motor-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["sim_motor-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["sim_motor-velocity"]["value"] == 3.0
    assert q.empty()


def test_motor_in_re(sim_motor: motor.Motor, RE) -> None:
    sim_motor.move(0)

    def my_plan():
        sim_motor.move(0)
        return
        yield

    with pytest.raises(RuntimeError, match="Will deadlock run engine if run in a plan"):
        RE(my_plan())
