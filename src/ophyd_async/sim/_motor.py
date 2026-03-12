import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from ophyd_async.core import (
    AsyncStatus,
    FlyMotorInfo,
    MovableLogic,
    SignalRW,
    StandardMovable,
    StandardReadable,
    WatchableAsyncStatus,
    error_if_none,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


@dataclass
class SimMotorMoveLogic(MovableLogic[float]):
    readback_set: Callable[[float], None]
    velocity: SignalRW[float]
    acceleration_time: SignalRW[float]
    _move_task: asyncio.Task | None = None

    async def stop(self) -> None:
        """Stop the motion."""
        await self.setpoint.set(await self.readback.get_value())
        if self._move_task is not None:
            self._move_task.cancel()

    async def _internal_sim_move(self, new_position: float) -> None:
        velocity = await self.velocity.get_value()
        old_position = await self.setpoint.get_value()
        if old_position == new_position:
            return

        await self.setpoint.set(new_position)
        if velocity == 0:
            self.readback_set(new_position)
            return

        start = time.monotonic()
        acceleration_time = abs(await self.acceleration_time.get_value())
        sign = np.sign(new_position - old_position)
        velocity = abs(velocity) * sign
        # The total distance to move
        total_distance = new_position - old_position
        # The ramp distance is the distance taken to ramp up (the same distance
        # is taken to ramp down). This is the area under the triangle of the
        # velocity ramp up (base * height / 2)
        ramp_distance = acceleration_time * velocity / 2
        if abs(ramp_distance * 2) >= abs(total_distance):
            # All time is ramp up and down, so recalculate the maximum velocity
            # we get to. We know the area under the ramp up triangle is half the
            # total distance, and we also know the ratio of velocity over
            # acceleration_time is the same as the ration of max_velocity over
            # ramp_time, so solve the simultaneous equations to get
            # max_velocity and ramp_time.
            max_velocity = np.sqrt(total_distance * velocity / acceleration_time) * sign
            ramp_time = total_distance / max_velocity
            # So move time is just the ramp up and ramp down with no constant
            # velocity section
            move_time = 2 * ramp_time
        else:
            # Middle segments of constant velocity
            max_velocity = velocity
            # Ramp up and down time is exactly the requested acceleration time
            ramp_time = acceleration_time
            # So move time is twice this, plus the time taken to move the
            # remaining distance at constant velocity
            move_time = ramp_time * 2 + (total_distance - ramp_distance * 2) / velocity
        # Make an array of relative update times at 10Hz intervals
        update_times = list(np.arange(0.1, move_time, 0.1, dtype=float))
        # With the end position appended
        if update_times and np.isclose(update_times[-1], move_time):
            update_times[-1] = move_time
        else:
            update_times.append(move_time)
        # Iterate through the update times, calculating new position for each
        for t in update_times:
            if t <= ramp_time:
                # Ramp up phase, calculate area under the ramp up triangle
                current_velocity = t / ramp_time * max_velocity
                position = old_position + current_velocity * t / 2
            elif t >= move_time - ramp_time:
                # Ramp down phase, subtract area under the ramp down triangle
                time_left = move_time - t
                current_velocity = time_left / ramp_time * max_velocity
                position = new_position - current_velocity * time_left / 2
            else:
                # Constant velocity phase
                position = old_position + ramp_distance + (t - ramp_time) * max_velocity
            # Calculate how long to wait to get there
            relative_time = time.monotonic() - start
            await asyncio.sleep(t - relative_time)
            # Update the readback position
            self.readback_set(position)

    async def move(self, new_position: float, timeout: float | None) -> None:
        # Needed so stop can successfully stop the task.
        self._move_task = asyncio.create_task(self._internal_sim_move(new_position))
        # If stop is called then this will raise a CancelledError, ignore it
        with contextlib.suppress(asyncio.CancelledError):
            await self._move_task


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
                float, 0, units=units
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
    def movable_logic(self):
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
        await self.velocity.set(value.velocity)

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
