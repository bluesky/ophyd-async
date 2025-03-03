import asyncio
import contextlib
import time

import numpy as np
from bluesky.protocols import Movable, Stoppable
from pydantic import BaseModel, ConfigDict, Field

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


class FlySimMotorInfo(BaseModel):
    """Minimal set of information required to fly a [](#SimMotor)."""

    model_config = ConfigDict(frozen=True)

    cv_start: float
    """Absolute position of the motor once it finishes accelerating to desired
    velocity, in motor EGUs"""

    cv_end: float
    """Absolute position of the motor once it begins decelerating from desired
    velocity, in EGUs"""

    cv_time: float = Field(gt=0)
    """Time taken for the motor to get from start_position to end_position, excluding
    run-up and run-down, in seconds."""

    @property
    def velocity(self) -> float:
        """Calculate the velocity of the constant velocity phase."""
        return (self.cv_end - self.cv_start) / self.cv_time

    def start_position(self, acceleration_time: float) -> float:
        """Calculate the start position with run-up distance added on."""
        return self.cv_start - acceleration_time * self.velocity / 2

    def end_position(self, acceleration_time: float) -> float:
        """Calculate the end position with run-down distance added on."""
        return self.cv_end + acceleration_time * self.velocity / 2


class SimMotor(StandardReadable, Movable, Stoppable):
    """For usage when simulating a motor."""

    def __init__(self, name="", instant=True) -> None:
        """Simulate a motor, with optional velocity.

        :param name: name of device
        :param instant: whether to move instantly or calculate move time using velocity
        """
        # Define some signals
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback, self._user_readback_set = soft_signal_r_and_setter(
                float, 0
            )
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.velocity = soft_signal_rw(float, 0 if instant else 1.0)
            self.acceleration_time = soft_signal_rw(float, 0.5)
            self.units = soft_signal_rw(str, "mm")
        self.user_setpoint = soft_signal_rw(float, 0)

        # Whether set() should complete successfully or not
        self._set_success = True
        self._move_status: AsyncStatus | None = None
        # Stored in prepare
        self._fly_info: FlySimMotorInfo | None = None
        # Set on kickoff(), complete when motor reaches end position
        self._fly_status: WatchableAsyncStatus | None = None

        super().__init__(name=name)

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    @AsyncStatus.wrap
    async def prepare(self, value: FlySimMotorInfo):
        """Calculate run-up and move there, setting fly velocity when there."""
        self._fly_info = value
        # Move to start as fast as we can
        await self.velocity.set(0)
        await self.set(value.start_position(await self.acceleration_time.get_value()))
        # Set the velocity for the actual move
        await self.velocity.set(value.velocity)

    @AsyncStatus.wrap
    async def kickoff(self):
        """Begin moving motor from prepared position to final position."""
        if not self._fly_info:
            msg = "Motor must be prepared before attempting to kickoff"
            raise RuntimeError(msg)
        acceleration_time = await self.acceleration_time.get_value()
        self._fly_status = self.set(self._fly_info.end_position(acceleration_time))
        # Wait for the acceleration time to ensure we are at velocity
        await asyncio.sleep(acceleration_time)

    def complete(self) -> WatchableAsyncStatus:
        """Mark as complete once motor reaches completed position."""
        if not self._fly_status:
            msg = "kickoff not called"
            raise RuntimeError(msg)
        return self._fly_status

    async def _move(self, old_position: float, new_position: float, velocity: float):
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
            self._user_readback_set(position)

    @WatchableAsyncStatus.wrap
    async def set(self, value: float):
        """Asynchronously move the motor to a new position."""
        new_position = value
        # Make sure any existing move tasks are stopped
        await self.stop()
        old_position, units, velocity = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.units.get_value(),
            self.velocity.get_value(),
        )
        # If zero velocity, do instant move
        if velocity == 0:
            self._user_readback_set(new_position)
        else:
            self._move_status = AsyncStatus(
                self._move(old_position, new_position, velocity)
            )
            # If stop is called then this will raise a CancelledError, ignore it
            with contextlib.suppress(asyncio.CancelledError):
                async for current_position in observe_value(
                    self.user_readback, done_status=self._move_status
                ):
                    yield WatcherUpdate(
                        current=current_position,
                        initial=old_position,
                        target=new_position,
                        name=self.name,
                        unit=units,
                    )
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=True):
        """Stop the motor if it is moving."""
        self._set_success = success
        if self._move_status:
            self._move_status.task.cancel()
            self._move_status = None
        await self.user_setpoint.set(await self.user_readback.get_value())
