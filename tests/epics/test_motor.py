import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    AsyncStatus,
    FlyMotorInfo,
    init_devices,
    observe_value,
    soft_signal_rw,
)
from ophyd_async.epics import motor
from ophyd_async.testing import (
    StatusWatcher,
    callback_on_mock_put,
    get_mock_put,
    mock_puts_blocked,
    set_mock_put_proceeds,
    set_mock_value,
    wait_for_pending_wakeups,
)


@pytest.fixture
async def sim_motor():
    async with init_devices(mock=True):
        sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X", name="sim_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.velocity, 1)
    yield sim_motor


async def test_motor_moving_well(sim_motor: motor.Motor) -> None:
    set_mock_put_proceeds(sim_motor.user_setpoint, False)
    s = sim_motor.set(0.55)
    watcher = StatusWatcher(s)
    await watcher.wait_for_call(
        name="sim_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.1),
    )
    assert 0.55 == await sim_motor.user_setpoint.get_value()
    assert not s.done
    await asyncio.sleep(0.1)
    set_mock_value(sim_motor.user_readback, 0.1)
    await watcher.wait_for_call(
        name="sim_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.1),
    )
    set_mock_put_proceeds(sim_motor.user_setpoint, True)
    await wait_for_pending_wakeups()
    assert s.done


async def test_motor_move_timeout(sim_motor: motor.Motor):
    class MyTimeout(Exception):
        pass

    def do_timeout(value, wait):
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
        time_elapsed=pytest.approx(0.0, abs=0.2),
    )


async def test_motor_moving_stopped(sim_motor: motor.Motor):
    set_mock_value(sim_motor.motor_done_move, False)
    set_mock_put_proceeds(sim_motor.user_setpoint, False)
    s = sim_motor.set(1.5)
    s.add_callback(Mock())
    await asyncio.sleep(0.2)
    assert not s.done
    await sim_motor.stop()

    # Note: needs to explicitly be called with 1, not just processed.
    # See https://epics.anl.gov/bcda/synApps/motor/motorRecord.html#Fields_command
    get_mock_put(sim_motor.motor_stop).assert_called_once_with(1, wait=False)

    set_mock_put_proceeds(sim_motor.user_setpoint, True)
    await wait_for_pending_wakeups()
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
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["sim_motor-velocity"]["value"] == 1.0
    await v.set(-2.0)
    assert (await q.get())["sim_motor-velocity"]["value"] == -2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["sim_motor-velocity"]["value"] == 3.0
    assert q.empty()


async def test_set_with_zero_velocity(sim_motor: motor.Motor) -> None:
    await sim_motor.velocity.set(0)
    with pytest.raises(ValueError, match="Mover has zero velocity"):
        await sim_motor.set(3.14)


@pytest.mark.parametrize(
    "setpoint, velocity, timeout",
    [
        (1, 1, CALCULATE_TIMEOUT),
        (-1, -1, CALCULATE_TIMEOUT),
        (1, -1, CALCULATE_TIMEOUT),
        (-1, 1, CALCULATE_TIMEOUT),
        (1, 1, 1),
        (-1, -1, 1),
        (1, -1, 1),
        (-1, 1, 1),
    ],
)
async def test_set(sim_motor: motor.Motor, setpoint, velocity, timeout) -> None:
    await sim_motor.velocity.set(velocity)
    await sim_motor.set(setpoint, timeout=timeout)
    assert (await sim_motor.locate()).get("setpoint") == setpoint


async def test_prepare_velocity_limit_error(sim_motor: motor.Motor):
    set_mock_value(sim_motor.max_velocity, 10)
    with pytest.raises(motor.MotorLimitsException):
        fly_info = FlyMotorInfo(start_position=-10, end_position=0, time_for_move=0.9)
        await sim_motor.prepare(fly_info)


async def test_valid_prepare_velocity(sim_motor: motor.Motor):
    set_mock_value(sim_motor.low_limit_travel, -10.01)
    set_mock_value(sim_motor.high_limit_travel, 20.01)
    set_mock_value(sim_motor.max_velocity, 10)
    fly_info = FlyMotorInfo(start_position=-10, end_position=0, time_for_move=1)
    await sim_motor.prepare(fly_info)
    assert (
        await sim_motor.velocity.get_value() == await sim_motor.max_velocity.get_value()
    )


@pytest.mark.parametrize(
    "acceleration_time, velocity, start_position, end_position, upper_limit,\
    lower_limit",
    [
        (1, 10, 0, 10, 30, -4.999),  # Goes below lower_limit, +ve direction
        (1, 10, 0, 10, 14.99, -10),  # Goes above upper_limit, +ve direction
        (1, 10, 10, 0, -30, -9.999),  # Goes below lower_limit, -ve direction
        (1, 10, 10, 0, 14.99, -10),  # Goes above upper_limit, -ve direction
    ],
)
async def test_prepare_motor_limits_error(
    sim_motor: motor.Motor,
    acceleration_time,
    velocity,
    start_position,
    end_position,
    upper_limit,
    lower_limit,
):
    set_mock_value(sim_motor.acceleration_time, acceleration_time)
    set_mock_value(sim_motor.low_limit_travel, lower_limit)
    set_mock_value(sim_motor.high_limit_travel, upper_limit)
    time_for_move = abs(end_position - start_position) / velocity
    fly_info = FlyMotorInfo(
        start_position=start_position,
        end_position=end_position,
        time_for_move=time_for_move,
    )
    with pytest.raises(motor.MotorLimitsException):
        await sim_motor.prepare(fly_info)


async def test_prepare_valid_limits(sim_motor: motor.Motor):
    set_mock_value(sim_motor.acceleration_time, 1)
    set_mock_value(sim_motor.low_limit_travel, -10.01)
    set_mock_value(sim_motor.high_limit_travel, 20.01)
    set_mock_value(sim_motor.max_velocity, 10)
    fly_info = motor.FlyMotorInfo(
        start_position=0,
        end_position=10,
        time_for_move=1,
    )
    await sim_motor.prepare(fly_info)
    assert await sim_motor.user_setpoint.get_value() == -5

    assert (
        fly_info.ramp_down_end_pos(await sim_motor.acceleration_time.get_value()) == 15
    )
    fly_info = motor.FlyMotorInfo(
        start_position=12,
        end_position=2,
        time_for_move=1,
    )
    await sim_motor.prepare(fly_info)
    assert await sim_motor.user_setpoint.get_value() == 17
    assert (
        fly_info.ramp_down_end_pos(await sim_motor.acceleration_time.get_value()) == -3
    )


@pytest.mark.parametrize(
    "expected_velocity, target_position",
    [
        (10, -10),
        (8, 8),
    ],
)
async def test_prepare(
    sim_motor: motor.Motor, target_position: float, expected_velocity: float
):
    set_mock_value(sim_motor.acceleration_time, 1)
    set_mock_value(sim_motor.low_limit_travel, -15)
    set_mock_value(sim_motor.high_limit_travel, 20)
    set_mock_value(sim_motor.max_velocity, 10)
    fake_set_signal = soft_signal_rw(float)
    await fake_set_signal.connect()

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
        motor.FlyMotorInfo(
            start_position=0,
            end_position=target_position,
            time_for_move=1,
        )
    )
    # Test that prepare is not marked as complete until correct position is reached
    await asyncio.gather(do_set(status), wait_for_status(status))
    assert await sim_motor.velocity.get_value() == expected_velocity
    assert status.done


async def test_kickoff(sim_motor: motor.Motor):
    sim_motor.set = MagicMock()
    with pytest.raises(
        RuntimeError, match="Motor must be prepared before attempting to kickoff"
    ):
        await sim_motor.kickoff()
    # TODO: why was this called _twice_?
    # with pytest.raises(RuntimeError):
    #     await sim_motor.kickoff()
    set_mock_value(sim_motor.acceleration_time, 1)
    sim_motor._fly_info = motor.FlyMotorInfo(
        start_position=12,
        end_position=2,
        time_for_move=1,
    )
    await sim_motor.kickoff()
    sim_motor.set.assert_called_once_with(-3.0, timeout=CALCULATE_TIMEOUT)


async def test_complete(sim_motor: motor.Motor) -> None:
    with pytest.raises(RuntimeError, match="kickoff not called"):
        sim_motor.complete()
    sim_motor._fly_status = sim_motor.set(20)
    assert not sim_motor._fly_status.done
    await sim_motor.complete()
    assert sim_motor._fly_status.done


async def test_locatable(sim_motor: motor.Motor) -> None:
    callback_on_mock_put(
        sim_motor.user_setpoint,
        lambda x, *_, **__: set_mock_value(sim_motor.user_readback, x),
    )
    assert (await sim_motor.locate())["readback"] == 0
    with mock_puts_blocked(sim_motor.user_setpoint):
        move_status = sim_motor.set(10)
        assert (await sim_motor.locate())["readback"] == 0
    await move_status
    assert (await sim_motor.locate())["readback"] == 10
    assert (await sim_motor.locate())["setpoint"] == 10
