import asyncio
from time import time
from typing import Optional

from bluesky.protocols import Flyable, Movable, Preparable, Stoppable
from pydantic import BaseModel, Field

from ophyd_async.core import (
    ConfigSignal,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
)
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.signal import observe_value
from ophyd_async.core.utils import (
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    CalculateTimeout,
    WatcherUpdate,
)

from ..signal.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class MotorLimitsException(Exception):
    pass


class InvalidFlyMotorException(Exception):
    pass


DEFAULT_MOTOR_FLY_TIMEOUT = 60
DEFAULT_WATCHER_UPDATE_FREQUENCY = 0.2


class FlyMotorInfo(BaseModel):
    """Minimal set of information required to fly a motor"""

    # Absolute position of the motor once it finishes accelerating to desired velocity,
    # in millimetres
    start_position: float

    # Absolute position of the motor once it begins decelerating from desired velocity,
    # in millimetres
    end_position: float

    # Time taken for the motor to get from start_position to end_position, in seconds
    time_for_move: float

    # Time taken for the motor 'complete' to finish
    complete_timeout: float = DEFAULT_MOTOR_FLY_TIMEOUT

    # Step size of the motor 'complete' to finish, as a decimal percentage, before
    # providing a watcher update. Must be between 0 and 1
    watcher_update_frequency: float = Field(
        default=DEFAULT_WATCHER_UPDATE_FREQUENCY, ge=0, le=1
    )

    # Time since kickoff completed. Setting this has no effect
    complete_time_elapsed: float = 0


class Motor(StandardReadable, Movable, Stoppable, Flyable, Preparable):
    """Device that moves a motor record"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(ConfigSignal):
            self.motor_egu = epics_signal_r(str, prefix + ".EGU")
            self.velocity = epics_signal_rw(float, prefix + ".VELO")

        with self.add_children_as_readables(HintedSignal):
            self.user_readback = epics_signal_r(float, prefix + ".RBV")

        self.user_setpoint = epics_signal_rw(float, prefix + ".VAL")
        self.max_velocity = epics_signal_r(float, prefix + ".VMAX")
        self.acceleration_time = epics_signal_rw(float, prefix + ".ACCL")
        self.precision = epics_signal_r(int, prefix + ".PREC")
        self.deadband = epics_signal_r(float, prefix + ".RDBD")
        self.motor_done_move = epics_signal_r(int, prefix + ".DMOV")
        self.low_limit_travel = epics_signal_rw(float, prefix + ".LLM")
        self.high_limit_travel = epics_signal_rw(float, prefix + ".HLM")

        self.motor_stop = epics_signal_x(prefix + ".STOP")
        # Whether set() should complete successfully or not
        self._set_success = True
        self.fly_info: Optional[FlyMotorInfo] = None
        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    # TODO convert resolution to mm?
    @AsyncStatus.wrap
    async def prepare(self, value: FlyMotorInfo):
        """Calculate required velocity and run-up distance, then if motor limits aren't
        breached, move to start position minus run-up distance"""

        self.fly_info = value

        # Velocity at which motor travels from start_position to end_position, in mm/s
        fly_velocity = abs(
            (value.start_position - value.end_position) / value.time_for_move
        )
        velocity_max = await self.max_velocity.get_value()
        if fly_velocity > velocity_max:
            raise MotorLimitsException(
                f"Velocity of {fly_velocity}mm/s was requested for a motor with "
                f"vmax of {velocity_max}mm/s"
            )
        await self.velocity.set(fly_velocity)

        # Distance required for motor to accelerate to fly_velocity before reaching
        # start_position, and distance required for motor to decelerate from
        # fly_velocity to zero after end_position
        self.fly_run_up_distance = (
            await self.acceleration_time.get_value()
        ) * fly_velocity

        if value.start_position < value.end_position:
            self.fly_direction = True  # Positive direction
        elif value.start_position > value.end_position:
            self.fly_direction = False  # Negative direction
        else:
            raise InvalidFlyMotorException(
                "Requested to fly a motor using identical start and end positions"
            )

        self.fly_prepared_position = value.start_position
        fly_prepare_position = (
            value.start_position - self.fly_run_up_distance
            if self.fly_direction
            else value.start_position + self.fly_run_up_distance
        )

        self.fly_target_position = value.end_position

        self.fly_completed_position = (
            value.end_position + self.fly_run_up_distance
            if self.fly_direction
            else value.end_position - self.fly_run_up_distance
        )

        motor_lower_limit = await self.low_limit_travel.get_value()
        motor_upper_limit = await self.high_limit_travel.get_value()

        if (
            fly_prepare_position < motor_lower_limit
            or fly_prepare_position > fly_prepare_position
            or self.fly_completed_position > motor_upper_limit
            or self.fly_completed_position < motor_upper_limit
        ):
            raise MotorLimitsException(
                f"Motor trajectory for requested fly goes from "
                f"{self.fly_prepared_position} mm to "
                f"{self.fly_completed_position}mm and motor limits are "
                f"{motor_lower_limit} <= x <= {motor_upper_limit} "
            )

        self.fly_complete_timeout = value.complete_timeout

        await self.set(fly_prepare_position)

    async def kickoff(self):
        async def has_motor_kicked_off():
            assert self.fly_info, "Motor must be prepared before attempting to kickoff"
            if self.fly_direction:
                async for value in observe_value(self.user_readback, timeout=60):
                    if value >= self.fly_prepared_position:
                        self.fly_info.complete_time_elapsed = time()
                        break
            else:
                async for value in observe_value(self.user_readback, timeout=60):
                    if value <= self.fly_prepared_position:
                        self.fly_info.complete_time_elapsed = time()
                        break

        await self.set(self.fly_completed_position)

        # Kickoff complete when motor reaches start position
        return AsyncStatus(has_motor_kicked_off())

    @WatchableAsyncStatus.wrap
    async def complete(self):
        assert (
            self.fly_info
        ), "Motor must be prepared and kicked off before attempting to complete"
        # Complete once motor has stopped moving
        next_update_threshold = self.fly_info.watcher_update_frequency
        distance_to_travel = self.fly_prepared_position - self.fly_target_position

        # Yield watcher based on move completion, using specified
        # watcher_update_frequency
        async for value in observe_value(
            self.user_readback, timeout=self.fly_complete_timeout
        ):
            percentage_complete = (
                abs(value - self.fly_prepared_position) / distance_to_travel
            )
            if percentage_complete >= next_update_threshold:
                next_update_threshold = (
                    (percentage_complete // self.fly_info.watcher_update_frequency) + 1
                ) * self.fly_info.watcher_update_frequency

                # Catch unlikely rounding error
                if round(next_update_threshold, 2) == round(percentage_complete, 2):
                    next_update_threshold += self.fly_info.watcher_update_frequency

                yield WatcherUpdate(
                    name=self.name,
                    current=value,
                    initial=self.fly_prepared_position,
                    target=self.fly_target_position,
                    unit="mm",
                    time_elapsed=self.fly_info.complete_time_elapsed,
                    time_remaining=self.fly_info.time_for_move
                    - self.fly_info.complete_time_elapsed,
                )

    @WatchableAsyncStatus.wrap
    async def set(
        self, new_position: float, timeout: CalculatableTimeout = CalculateTimeout
    ):
        self._set_success = True
        (
            old_position,
            units,
            precision,
            velocity,
            acceleration_time,
        ) = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.motor_egu.get_value(),
            self.precision.get_value(),
            self.velocity.get_value(),
            self.acceleration_time.get_value(),
        )
        if timeout is CalculateTimeout:
            assert velocity > 0, "Motor has zero velocity"
            timeout = (
                abs(new_position - old_position) / velocity
                + 2 * acceleration_time
                + DEFAULT_TIMEOUT
            )
        move_status = self.user_setpoint.set(new_position, wait=True, timeout=timeout)
        async for current_position in observe_value(
            self.user_readback, done_status=move_status
        ):
            yield WatcherUpdate(
                current=current_position,
                initial=old_position,
                target=new_position,
                name=self.name,
                unit=units,
                precision=precision,
            )
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False.
        await self.motor_stop.trigger(wait=False)
