"""Support for EPICS motor record.

https://github.com/epics-modules/motor
"""

import asyncio

from bluesky.protocols import (
    Flyable,
    Locatable,
    Location,
    Preparable,
    Reading,
    Stoppable,
    Subscribable,
)

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    AsyncStatus,
    CalculatableTimeout,
    Callback,
    FlyMotorInfo,
    StandardReadable,
    StrictEnum,
    WatchableAsyncStatus,
    WatcherUpdate,
    error_if_none,
    observe_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw, epics_signal_w

__all__ = ["MotorLimitsException", "Motor"]


class MotorLimitsException(Exception):
    """Exception for invalid motor limits."""

    pass


class OffsetMode(StrictEnum):
    VARIABLE = "Variable"
    FROZEN = "Frozen"


class UseSetMode(StrictEnum):
    USE = "Use"
    SET = "Set"


class Motor(
    StandardReadable,
    Locatable[float],
    Stoppable,
    Flyable,
    Preparable,
    Subscribable[float],
):
    """Device that moves a motor record."""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.motor_egu = epics_signal_r(str, prefix + ".EGU")
            self.velocity = epics_signal_rw(float, prefix + ".VELO")
            self.offset = epics_signal_rw(float, prefix + ".OFF")

        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback = epics_signal_r(float, prefix + ".RBV")

        self.user_setpoint = epics_signal_rw(float, prefix + ".VAL")
        self.max_velocity = epics_signal_r(float, prefix + ".VMAX")
        self.acceleration_time = epics_signal_rw(float, prefix + ".ACCL")
        self.precision = epics_signal_r(int, prefix + ".PREC")
        self.deadband = epics_signal_r(float, prefix + ".RDBD")
        self.motor_done_move = epics_signal_r(int, prefix + ".DMOV")
        self.low_limit_travel = epics_signal_rw(float, prefix + ".LLM")
        self.high_limit_travel = epics_signal_rw(float, prefix + ".HLM")
        self.offset_freeze_switch = epics_signal_rw(OffsetMode, prefix + ".FOFF")
        self.high_limit_switch = epics_signal_r(int, prefix + ".HLS")
        self.low_limit_switch = epics_signal_r(int, prefix + ".LLS")
        self.set_use_switch = epics_signal_rw(UseSetMode, prefix + ".SET")

        # Note:cannot use epics_signal_x here, as the motor record specifies that
        # we must write 1 to stop the motor. Simply processing the record is not
        # sufficient.
        self.motor_stop = epics_signal_w(int, prefix + ".STOP")

        # Whether set() should complete successfully or not
        self._set_success = True

        # Currently requested fly info, stored in prepare
        self._fly_info: FlyMotorInfo | None = None

        # Set on kickoff(), complete when motor reaches self._fly_completed_position
        self._fly_status: WatchableAsyncStatus | None = None

        super().__init__(name=name)

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        """Set name of the motor and its children."""
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    @AsyncStatus.wrap
    async def prepare(self, value: FlyMotorInfo):
        """Move to the beginning of a suitable run-up distance ready for a fly scan."""
        self._fly_info = value

        # Velocity, at which motor travels from start_position to end_position, in motor
        # egu/s.
        max_speed, egu = await asyncio.gather(
            self.max_velocity.get_value(), self.motor_egu.get_value()
        )
        if abs(value.velocity) > max_speed:
            raise MotorLimitsException(
                f"Velocity {abs(value.velocity)} {egu}/s was requested for a motor "
                f" with max speed of {max_speed} {egu}/s"
            )

        acceleration_time = await self.acceleration_time.get_value()
        ramp_up_start_pos = value.ramp_up_start_pos(acceleration_time)
        ramp_down_end_pos = value.ramp_down_end_pos(acceleration_time)

        motor_lower_limit, motor_upper_limit, egu = await asyncio.gather(
            self.low_limit_travel.get_value(),
            self.high_limit_travel.get_value(),
            self.motor_egu.get_value(),
        )

        if (
            not motor_upper_limit >= ramp_up_start_pos >= motor_lower_limit
            or not motor_upper_limit >= ramp_down_end_pos >= motor_lower_limit
        ):
            raise MotorLimitsException(
                f"Motor trajectory for requested fly is from "
                f"{ramp_up_start_pos}{egu} to "
                f"{ramp_down_end_pos}{egu} but motor limits are "
                f"{motor_lower_limit}{egu} <= x <= {motor_upper_limit}{egu} "
            )

        # move to prepare position at maximum velocity
        await self.velocity.set(abs(max_speed))
        await self.set(ramp_up_start_pos)

        # Set velocity we will be using for the fly scan
        await self.velocity.set(abs(value.velocity))

    @AsyncStatus.wrap
    async def kickoff(self):
        """Begin moving motor from prepared position to final position."""
        fly_info = error_if_none(
            self._fly_info, "Motor must be prepared before attempting to kickoff"
        )

        acceleration_time = await self.acceleration_time.get_value()
        self._fly_status = self.set(
            fly_info.ramp_down_end_pos(acceleration_time),
            timeout=fly_info.timeout,
        )

    def complete(self) -> WatchableAsyncStatus:
        """Mark as complete once motor reaches completed position."""
        fly_status = error_if_none(self._fly_status, "kickoff not called")
        return fly_status

    @WatchableAsyncStatus.wrap
    async def set(  # type: ignore
        self, new_position: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT
    ):
        """Move motor to the given value."""
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

        if timeout is CALCULATE_TIMEOUT:
            try:
                timeout = (
                    abs((new_position - old_position) / velocity)
                    + 2 * acceleration_time
                    + DEFAULT_TIMEOUT
                )
            except ZeroDivisionError as error:
                msg = "Mover has zero velocity"
                raise ValueError(msg) from error

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
        """Request to stop moving and return immediately."""
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self.motor_stop.set(1, wait=False)

    async def locate(self) -> Location[float]:
        """Return the current setpoint and readback of the motor."""
        setpoint, readback = await asyncio.gather(
            self.user_setpoint.get_value(), self.user_readback.get_value()
        )
        return Location(setpoint=setpoint, readback=readback)

    def subscribe(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Subscribe."""
        self.user_readback.subscribe(function)

    def clear_sub(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Unsubscribe."""
        self.user_readback.clear_sub(function)
