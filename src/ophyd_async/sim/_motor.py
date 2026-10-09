import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

from ophyd_async.core import (
    AsyncStatus,
    DeviceMock,
    FlyMotorInfo,
    MovableLogic,
    SignalRW,
    StandardMovable,
    StandardReadable,
    TimeoutCalculator,
    WatchableAsyncStatus,
    default_mock_class,
    error_if_none,
    simulate_move,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


@dataclass
class SimMotorMoveLogic(MovableLogic[float]):
    readback_set: Callable[[float], None]
    velocity: SignalRW[float]
    acceleration_time: SignalRW[float]

    async def stop(self) -> None:
        """Stop the motion."""
        await self.setpoint.set(await self.readback.get_value())

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        old_position, velocity, acceleration_time = await asyncio.gather(
            self.readback.get_value(),
            self.velocity.get_value(),
            self.acceleration_time.get_value(),
        )

        await self.setpoint.set(new_position)
        async for position in simulate_move(
            old_position, new_position, velocity, acceleration_time
        ):
            self.readback_set(position)


# Remove InstantMovableMock as SimMotor owns this logic, depends if instant=True/False
@default_mock_class(DeviceMock)
class SimMotor(StandardReadable, StandardMovable[float]):
    """For usage when simulating a motor."""

    def __init__(
        self,
        name: str = "",
        instant: bool = True,
        initial_value: float = 0.0,
        units: str = "mm",
    ) -> None:
        """Simulate a motor, with optional velocity.

        :param name: name of device
        :param instant: whether to move instantly or calculate move time using velocity
        :param initial_value: initial position of the motor
        :param units: units of the motor position
        """
        # Define some signals
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback, self._user_readback_set = soft_signal_r_and_setter(
                float, initial_value, units=units
            )
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.velocity = soft_signal_rw(float, 0 if instant else 1.0)
            self.acceleration_time = soft_signal_rw(float, 0.5)
        self.user_setpoint = soft_signal_rw(float, initial_value, units=units)

        # Stored in prepare
        self._fly_info: FlyMotorInfo | None = None
        # Set on kickoff(), complete when motor reaches end position
        self._fly_status: WatchableAsyncStatus | None = None

        super().__init__(name=name)

    @cached_property
    def standard_logic(self):
        return SimMotorMoveLogic(
            readback=self.user_readback,
            readback_set=self._user_readback_set,
            setpoint=self.user_setpoint,
            velocity=self.velocity,
            acceleration_time=self.acceleration_time,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: FlyMotorInfo):
        """Calculate run-up and move there, setting fly velocity when there."""
        self._fly_info = value
        # Move to start as fast as we can
        await self.velocity.set(0)
        await self.set(
            value.ramp_up_start_pos(await self.acceleration_time.get_value())
        )
        # Set the velocity for the actual move
        await self.velocity.set(value.speed)

    @AsyncStatus.wrap
    async def kickoff(self):
        """Begin moving motor from prepared position to final position."""
        fly_info = error_if_none(
            self._fly_info, "Motor must be prepared before attempting to kickoff"
        )
        acceleration_time = await self.acceleration_time.get_value()
        self._fly_status = self.set(fly_info.ramp_down_end_pos(acceleration_time))
        # Wait for the acceleration time to ensure we are at velocity
        await asyncio.sleep(acceleration_time)

    def complete(self) -> WatchableAsyncStatus:
        """Mark as complete once motor reaches completed position."""
        fly_status = error_if_none(self._fly_status, "kickoff not called")
        return fly_status
