import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    AsyncStatus,
    Device,
    DeviceMock,
    FlyMotorInfo,
    callback_on_mock_put,
    default_mock_class,
    get_mock_put,
    init_devices,
    mock_puts_blocked,
    observe_value,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_rw,
)
from ophyd_async.epics import motor
from ophyd_async.testing import (
    StatusWatcher,
    wait_for_pending_wakeups,
)


@pytest.fixture
async def sim_motor():
    async with init_devices(mock=True):
        sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X", name="sim_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.velocity, 1)
    # Widen limits to accommodate ramp distances in fly scan trajectories
    # (Previously dial limits were 0,0 which skipped all limit checks)
    set_mock_value(sim_motor.low_limit_travel, -11)
    set_mock_value(sim_motor.high_limit_travel, 21)
    set_mock_value(sim_motor.dial_low_limit_travel, -11)
    set_mock_value(sim_motor.dial_high_limit_travel, 21)
    yield sim_motor


@pytest.mark.xfail(reason="Flaky test")
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
    class MyError(Exception):
        pass

    def do_timeout(value, wait):
        # Raise custom exception to be clear it bubbles up
        raise MyError()

    callback_on_mock_put(sim_motor.user_setpoint, do_timeout)
    s = sim_motor.set(0.3)
    watcher = Mock()
    s.watch(watcher)
    with pytest.raises(MyError):
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
    v.subscribe_reading(q.put_nowait)
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
    "position, upper_limit, lower_limit",
    [
        (-10, 9.99, -9.99),  # Goes below lower_limit
        (10, 9.99, -9.99),  # Goes above upper_limit
    ],
)
async def test_move_outside_motor_limits_causes_error(
    sim_motor: motor.Motor,
    position,
    upper_limit,
    lower_limit,
):
    set_mock_value(sim_motor.velocity, 10)
    set_mock_value(sim_motor.dial_low_limit_travel, lower_limit)
    set_mock_value(sim_motor.dial_high_limit_travel, upper_limit)
    set_mock_value(sim_motor.low_limit_travel, lower_limit)
    set_mock_value(sim_motor.high_limit_travel, upper_limit)
    with pytest.raises(motor.MotorLimitsError):
        await sim_motor.set(position)


async def test_given_limits_of_0_0_then_move_causes_no_error(
    sim_motor: motor.Motor,
):
    set_mock_value(sim_motor.velocity, 10)
    set_mock_value(sim_motor.dial_low_limit_travel, 0)
    set_mock_value(sim_motor.dial_high_limit_travel, 0)
    set_mock_value(sim_motor.low_limit_travel, -0.001)
    set_mock_value(sim_motor.high_limit_travel, 0.001)
    await sim_motor.set(100)
    assert (await sim_motor.user_setpoint.get_value()) == 100


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
    with pytest.raises(motor.MotorLimitsError):
        fly_info = FlyMotorInfo(start_position=-10, end_position=0, time_for_move=0.9)
        await sim_motor.prepare(fly_info)


async def test_valid_prepare_velocity(sim_motor: motor.Motor):
    # Widen user limits to accommodate ramp distances (trajectory goes to -10.5)
    set_mock_value(sim_motor.low_limit_travel, -11)
    set_mock_value(sim_motor.high_limit_travel, 21)
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
    with pytest.raises(motor.MotorLimitsError):
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


def test_core_notconnected_emits_deprecation_warning():
    with pytest.deprecated_call():
        from ophyd_async.epics.motor import MotorLimitsException  # noqa: F401


async def test_instant_motor_mock_auto_injection():
    """Test that InstantMotorMock is automatically used for Motor devices.

    This test verifies that the @default_device_mock_for_class decorator
    works correctly, automatically injecting the InstantMotorMock behavior
    when a Motor is connected in mock mode.
    """
    # Create a motor without manually setting up mock callbacks
    async with init_devices(mock=True):
        test_motor = motor.Motor("TEST:MOTOR")

    # The InstantMotorMock should have been automatically applied
    # Verify that setting the setpoint automatically updates the readback
    await test_motor.user_setpoint.set(42.0)
    readback = await test_motor.user_readback.get_value()
    assert readback == 42.0

    # Test with a different value to ensure it continues to work
    await test_motor.user_setpoint.set(100.5)
    readback = await test_motor.user_readback.get_value()
    assert readback == 100.5


async def test_instant_motor_mock_sets_done_flag():
    """Test that InstantMotorMock sets up motor_done_move flag correctly."""
    async with init_devices(mock=True):
        test_motor = motor.Motor("TEST:MOTOR")

    # Verify motor starts in "done" state
    assert await test_motor.motor_done_move.get_value() == 1

    # Verify motor_done_move toggles during movement (even if instant)
    await test_motor.user_setpoint.set(50.0)
    # After instant move, motor should be done again
    assert await test_motor.motor_done_move.get_value() == 1
    # And readback should have updated
    assert await test_motor.user_readback.get_value() == 50.0


async def test_motor_set_with_instant_mock():
    """Integration test: use motor.set() with InstantMotorMock.

    This verifies that InstantMotorMock provides all necessary default values
    (velocity, limits, etc.) so motor.set() works without errors.
    """
    async with init_devices(mock=True):
        test_motor = motor.Motor("BL01I-MO-TABLE-01:X")

    # Verify sensible defaults are set
    assert await test_motor.velocity.get_value() == 1000.0

    # Use motor.set() to move the motor - should work without errors
    status = test_motor.set(100.0)
    await status

    # Verify the move completed successfully
    assert status.done
    assert status.success
    assert await test_motor.user_readback.get_value() == 100.0

    # Test another move to ensure it continues to work
    status = test_motor.set(-50.0)
    await status
    assert status.success
    assert await test_motor.user_readback.get_value() == -50.0


async def test_device_mock_with_registered_subclass():
    """Test automatic mock with registered subclass using decorator."""
    # Motor has InstantMotorMock registered via @default_device_mock_for_class
    async with init_devices(mock=True):
        test_motor = motor.Motor("TEST:MOTOR")

    # Should use InstantMotorMock automatically
    await test_motor.user_setpoint.set(50.0)
    assert await test_motor.user_readback.get_value() == 50.0


async def test_device_mock_with_base_device():
    """Test automatic mock with base Device class (no registered mock)."""

    class CustomDevice(Device):
        """A device with no registered DeviceMock."""

        pass

    async with init_devices(mock=True):
        test_device = CustomDevice()

    # Should use plain DeviceMock as fallback
    assert isinstance(test_device._mock, DeviceMock)
    assert type(test_device._mock) is DeviceMock


async def test_device_mock_explicit_instance():
    """Test passing an explicit DeviceMock instance."""
    # Note: This test doesn't actually register a custom mock to avoid
    # polluting the global registry for other tests. Instead, it just
    # verifies that an explicitly passed DeviceMock is used.

    # Use explicit mock instance (should be used as-is)
    explicit_mock = DeviceMock()  # Plain mock, no custom behavior
    test_motor = motor.Motor("TEST:MOTOR")
    await test_motor.connect(mock=explicit_mock)

    # Verify the explicit mock was used (not InstantMotorMock)
    # The explicit mock has no callback, so readback won't update automatically
    await test_motor.user_setpoint.set(10.0)
    # Readback should still be at default (0) because explicit mock has no behavior
    assert await test_motor.user_readback.get_value() == 0.0

    # Verify that InstantMotorMock would have worked if we hadn't passed explicit mock
    test_motor2 = motor.Motor("TEST:MOTOR2")
    await test_motor2.connect(mock=True)  # Use default InstantMotorMock
    await test_motor2.user_setpoint.set(20.0)
    assert await test_motor2.user_readback.get_value() == 20.0


async def test_device_mock_inheritance():
    """Test that subclass can inherit parent's registered mock."""

    class BaseTestDeviceMock(DeviceMock["BaseTestDevice"]):
        async def connect(self, device: "BaseTestDevice") -> None:
            device.mock_was_called = True

    @default_mock_class(BaseTestDeviceMock)
    class BaseTestDevice(Device):
        """Base device for testing."""

    class DerivedTestDevice(BaseTestDevice):
        """Derived device with no explicit mock."""

    # DerivedTestDevice should inherit BaseTestDevice's mock
    async with init_devices(mock=True):
        test_device = DerivedTestDevice()

    # Verify the BaseTestDeviceMock was used
    assert getattr(test_device, "mock_was_called", False)


async def test_instant_motor_mock_recursive_in_composite_device():
    """Test that InstantMotorMock is applied recursively to child motors.

    This addresses DominicOram's feedback that child motors in composite
    devices should automatically get InstantMotorMock behavior when the
    parent is connected in mock mode.
    """

    class XYStage(Device):
        """A composite device containing two motors."""

        def __init__(self, prefix: str, name: str = ""):
            self.x = motor.Motor(prefix + "X")
            self.y = motor.Motor(prefix + "Y")
            super().__init__(name=name)

    # Connect composite device in mock mode
    async with init_devices(mock=True):
        stage = XYStage("BL01I-MO-STAGE-01:")

    # Verify child motors have InstantMotorMock behavior
    # X motor should instantly update readback when setpoint is written
    await stage.x.user_setpoint.set(100.0)
    assert await stage.x.user_readback.get_value() == 100.0

    # Y motor should also have the behavior
    await stage.y.user_setpoint.set(-50.0)
    assert await stage.y.user_readback.get_value() == -50.0

    # Verify motor.set() works on child motors
    status = stage.x.set(200.0)
    await status
    assert status.success
    assert await stage.x.user_readback.get_value() == 200.0


async def test_instant_motor_mock_preserves_parent_mock_tracking():
    """Test that parent mock call tracking works with InstantMotorMock."""

    class XYStage(Device):
        def __init__(self, prefix: str, name: str = ""):
            self.x = motor.Motor(prefix + "X")
            self.y = motor.Motor(prefix + "Y")
            super().__init__(name=name)

    stage = XYStage("BL01I-MO-STAGE-01:")
    parent_mock = DeviceMock()
    await stage.connect(mock=parent_mock)

    # Make some operations on child motors
    await stage.x.user_setpoint.set(100.0)
    await stage.y.user_setpoint.set(-50.0)

    # Verify we can track calls on the parent mock
    parent_mock_obj = parent_mock()
    assert parent_mock_obj.x.user_setpoint.put.called
    assert parent_mock_obj.y.user_setpoint.put.called

    # Verify the mock calls include the child operations
    assert any("x" in str(call) for call in parent_mock_obj.mock_calls)
    assert any("y" in str(call) for call in parent_mock_obj.mock_calls)
