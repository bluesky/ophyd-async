import asyncio
import time
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    DeviceCollector,
    set_mock_put_proceeds,
    set_mock_value,
)
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.mock_signal_backend import MockSignalBackend
from ophyd_async.core.mock_signal_utils import callback_on_mock_put
from ophyd_async.core.signal import SignalRW, observe_value
from ophyd_async.core.utils import CalculateTimeout
from ophyd_async.epics.motion import motor
from ophyd_async.epics.motion.motor import (
    FlyMotorInfo,
    MotorLimitsException,
)

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


async def test_prepare_velocity_errors(sim_motor: motor.Motor):
    set_mock_value(sim_motor.max_velocity, 10)
    with pytest.raises(MotorLimitsException):
        fly_info = FlyMotorInfo(start_position=-10, end_position=0, time_for_move=0.9)
        await sim_motor._prepare_velocity(
            fly_info.start_position,
            fly_info.end_position,
            fly_info.time_for_move,
        )


async def test_valid_prepare_velocity(sim_motor: motor.Motor):
    set_mock_value(sim_motor.max_velocity, 10)
    fly_info = FlyMotorInfo(start_position=-10, end_position=0, time_for_move=1)
    await sim_motor._prepare_velocity(
        fly_info.start_position,
        fly_info.end_position,
        fly_info.time_for_move,
    )
    assert await sim_motor.velocity.get_value() == 10


@pytest.mark.parametrize(
    "acceleration_time, velocity, start_position, end_position, upper_limit,\
    lower_limit",
    [
        (1, 10, 0, 10, 30, -9.999),  # Goes below lower_limit, +ve direction
        (1, 10, 0, 10, 19.99, -10),  # Goes above upper_limit, +ve direction
        (1, -10, 10, 0, -30, -9.999),  # Goes below lower_limit, -ve direction
        (1, -10, 10, 0, 19.99, -10),  # Goes above upper_limit, -ve direction
    ],
)
async def test_prepare_motor_path_errors(
    sim_motor: motor.Motor,
    acceleration_time,
    velocity,
    start_position,
    end_position,
    upper_limit,
    lower_limit,
):
    set_mock_value(sim_motor.max_velocity, 1)
    set_mock_value(sim_motor.acceleration_time, acceleration_time)
    set_mock_value(sim_motor.low_limit_travel, lower_limit)
    set_mock_value(sim_motor.high_limit_travel, upper_limit)
    with pytest.raises(MotorLimitsException):
        await sim_motor._prepare_motor_path(velocity, start_position, end_position)


async def test_prepare_motor_path(sim_motor: motor.Motor):
    set_mock_value(sim_motor.acceleration_time, 1)
    set_mock_value(sim_motor.max_velocity, 1)
    set_mock_value(sim_motor.low_limit_travel, -10.01)
    set_mock_value(sim_motor.high_limit_travel, 20.01)
    fly_info = FlyMotorInfo(
        start_position=0,
        end_position=10,
        time_for_move=1,
    )
    assert (
        await sim_motor._prepare_motor_path(
            10, fly_info.start_position, fly_info.end_position
        )
        == -10
    )
    assert sim_motor._fly_completed_position == 20


async def test_prepare(sim_motor: motor.Motor):
    set_mock_value(sim_motor.acceleration_time, 1)
    set_mock_value(sim_motor.low_limit_travel, -10)
    set_mock_value(sim_motor.high_limit_travel, 20)
    set_mock_value(sim_motor.max_velocity, 10)
    fake_set_signal = SignalRW(MockSignalBackend(float))
    target_position = 10

    async def wait_for_set(_):
        async for value in observe_value(fake_set_signal, timeout=1):
            if value == target_position:
                break

    sim_motor.set = AsyncMock(side_effect=wait_for_set)

    async def do_set(status: AsyncStatus):
        assert not status.done
        await fake_set_signal.set(target_position)

    async def wait_for_status(status: AsyncStatus):
        await status

    status = sim_motor.prepare(
        FlyMotorInfo(
            start_position=0,
            end_position=target_position,
            time_for_move=1,
        )
    )
    # Test that prepare is not marked as complete until correct position is reached
    await asyncio.gather(do_set(status), wait_for_status(status))
    assert status.done


async def test_kickoff(sim_motor: motor.Motor):
    sim_motor.set = MagicMock()
    with pytest.raises(AssertionError):
        await sim_motor.kickoff()
    with pytest.raises(AssertionError):
        await sim_motor.kickoff()
    sim_motor._fly_completed_position = 20
    await sim_motor.kickoff()
    sim_motor.set.assert_called_once_with(20, timeout=CalculateTimeout)


async def test_complete(sim_motor: motor.Motor) -> None:
    with pytest.raises(AssertionError):
        sim_motor.complete()
    sim_motor._fly_status = sim_motor.set(20)
    assert not sim_motor._fly_status.done
    await sim_motor.complete()
    assert sim_motor._fly_status.done
