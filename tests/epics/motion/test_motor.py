import asyncio
from typing import Dict
from unittest.mock import Mock, call

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import DeviceCollector, set_mock_put_proceeds, set_mock_value
from ophyd_async.epics.motion import motor

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_BIT = 0.001


@pytest.fixture
async def mock_motor():
    async with DeviceCollector(mock=True):
        mock_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        # Signals connected here

    assert mock_motor.name == "mock_motor"
    set_mock_value(mock_motor.units, "mm")
    set_mock_value(mock_motor.precision, 3)
    set_mock_value(mock_motor.velocity, 1)
    yield mock_motor


async def test_motor_moving_well(mock_motor: motor.Motor) -> None:
    set_mock_put_proceeds(mock_motor.setpoint, False)
    s = mock_motor.set(0.55)
    watcher = Mock()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await asyncio.sleep(A_BIT)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="mock_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )
    watcher.reset_mock()
    assert 0.55 == await mock_motor.setpoint.get_value()
    assert not s.done
    await asyncio.sleep(0.1)
    set_mock_value(mock_motor.readback, 0.1)
    assert watcher.call_count == 1
    assert watcher.call_args == call(
        name="mock_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_mock_put_proceeds(mock_motor.setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    done.assert_called_once_with(s)


async def test_motor_moving_stopped(mock_motor: motor.Motor):
    set_mock_put_proceeds(mock_motor.setpoint, False)
    s = mock_motor.set(1.5)
    s.add_callback(Mock())
    await asyncio.sleep(0.2)
    assert not s.done
    await mock_motor.stop()
    set_mock_put_proceeds(mock_motor.setpoint, True)
    await asyncio.sleep(A_BIT)
    assert s.done
    assert s.success is False


async def test_read_motor(mock_motor: motor.Motor):
    mock_motor.stage()
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.0
    assert (await mock_motor.describe())["mock_motor"][
        "source"
    ] == "mock://BLxxI-MO-TABLE-01:X.RBV"
    assert (await mock_motor.read_configuration())["mock_motor-velocity"]["value"] == 1
    assert (await mock_motor.describe_configuration())["mock_motor-units"]["shape"] == []
    set_mock_value(mock_motor.readback, 0.5)
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.5
    mock_motor.unstage()
    # Check we can still read and describe when not staged
    set_mock_value(mock_motor.readback, 0.1)
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.1
    assert await mock_motor.describe()


async def test_set_velocity(mock_motor: motor.Motor) -> None:
    v = mock_motor.velocity
    assert (await v.describe())["mock_motor-velocity"][
        "source"
    ] == "mock://BLxxI-MO-TABLE-01:X.VELO"
    q: asyncio.Queue[Dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["mock_motor-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["mock_motor-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["mock_motor-velocity"]["value"] == 3.0
    assert q.empty()


def test_motor_in_re(mock_motor: motor.Motor, RE) -> None:
    mock_motor.move(0)

    def my_plan():
        mock_motor.move(0)
        return
        yield

    with pytest.raises(RuntimeError, match="Will deadlock run engine if run in a plan"):
        RE(my_plan())
