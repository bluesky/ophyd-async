"""Support for EPICS motor record.

https://github.com/epics-modules/motor
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import cached_property

from bluesky.protocols import Flyable, Preparable

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DeviceMock,
    FlyMotorInfo,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalW,
    StandardMovable,
    StandardReadable,
    StrictEnum,
    WatchableAsyncStatus,
    callback_on_mock_put,
    default_mock_class,
    error_if_none,
    set_mock_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw, epics_signal_w

__all__ = ["MotorLimitsError", "Motor", "InstantMotorMock", "OffsetMode", "UseSetMode"]


class MotorLimitsError(Exception):
    """Exception for invalid motor limits."""

    pass


# Back compat - delete before 1.0
def __getattr__(name):
    import warnings

    renames = {
        "MotorLimitsException": MotorLimitsError,
    }
    rename = renames.get(name)
    if rename is not None:
        warnings.warn(
            DeprecationWarning(
                f"{name!r} is deprecated, use {rename.__name__!r} instead"
            ),
            stacklevel=2,
        )
        return rename
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class OffsetMode(StrictEnum):
    """In Set mode, determine what to do when the motor setpoint is written."""

    VARIABLE = "Variable"
    """Change the offset so the readback matches the setpoint."""
    FROZEN = "Frozen"
    """Tell the controller to change the readback without changing the offset."""


class UseSetMode(StrictEnum):
    """Determine what to do when the motor setpoint is written."""

    USE = "Use"
    """Tell the controller to move to the setpoint."""
    SET = "Set"
    """Change offset (in record or in controller) when setpoint is written."""


@dataclass
class MotorMoveLogic(MovableLogic[float]):
    """Add the specific logic for moving a motor."""

    readback: SignalR[float]
    setpoint: SignalRW[float]
    motor_stop: SignalW[int]
    low_limit_travel: SignalRW[float]
    high_limit_travel: SignalRW[float]
    motor_egu: SignalR[str]
    dial_low_limit_travel: SignalRW[float]
    dial_high_limit_travel: SignalRW[float]
    velocity: SignalRW[float]
    acceleration_time: SignalRW[float]
    precision: SignalR[int]

    async def stop(self):
        """Request to stop moving."""
        await self.motor_stop.set(1)

    async def check_move(self, old_position: float, new_position: float):
        """Check the positions are within limits.

        Will raise a MotorLimitsException if the given absolute positions will be
        outside the motor soft limits.
        """
        (
            motor_lower_limit,
            motor_upper_limit,
            egu,
            dial_lower_limit,
            dial_upper_limit,
        ) = await asyncio.gather(
            self.low_limit_travel.get_value(),
            self.high_limit_travel.get_value(),
            self.motor_egu.get_value(),
            self.dial_low_limit_travel.get_value(),
            self.dial_high_limit_travel.get_value(),
        )

        # EPICS motor record treats dial limits of 0, 0 as no limit
        # Use DLLM and DHLM to check
        if dial_lower_limit == 0 and dial_upper_limit == 0:
            return

        # Use real motor limit(i.e. HLM and LLM) to check if the move is permissible
        if (
            not motor_upper_limit >= old_position >= motor_lower_limit
            or not motor_upper_limit >= new_position >= motor_lower_limit
        ):
            name = self.readback.name
            raise MotorLimitsError(
                f"{name} motor trajectory for requested fly/move is from "
                f"{old_position}{egu} to "
                f"{new_position}{egu} but motor limits are "
                f"{motor_lower_limit}{egu} <= x <= {motor_upper_limit}{egu} "
                f"dial limits are "
                f"{dial_lower_limit}{egu} <= x <= {dial_upper_limit}."
            )

    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        (
            velocity,
            acceleration_time,
        ) = await asyncio.gather(
            self.velocity.get_value(),
            self.acceleration_time.get_value(),
        )
        try:
            return (
                abs((new_position - old_position) / velocity)
                + 2 * acceleration_time
                + DEFAULT_TIMEOUT
            )
        except ZeroDivisionError as error:
            msg = f"Motor {self.readback.name} has zero velocity."
            raise ValueError(msg) from error

    async def get_units_precision(self) -> tuple[str | None, int | None]:
        return await asyncio.gather(
            self.motor_egu.get_value(),
            self.precision.get_value(),
        )


class InstantMotorMock(DeviceMock["Motor"]):
    """Mock behaviour that instantly moves readback to setpoint."""

    async def connect(self, device: Motor) -> None:
        """Mock signals to do an instant move on setpoint write."""
        # Set sensible defaults to avoid runtime errors
        set_mock_value(device.velocity, 1000)  # Prevent ZeroDivisionError
        set_mock_value(device.max_velocity, 1000)  # Prevent ZeroDivisionError

        # Motor starts in "done" state (not moving)
        set_mock_value(device.motor_done_move, 1)

        # When setpoint is written to, immediately update readback and done flag
        def _instant_move(value):
            set_mock_value(device.motor_done_move, 0)  # Moving
            set_mock_value(device.user_readback, value)  # Arrive instantly
            set_mock_value(device.motor_done_move, 1)  # Done

        callback_on_mock_put(device.user_setpoint, _instant_move)


@default_mock_class(InstantMotorMock)
class Motor(StandardMovable, StandardReadable, Flyable, Preparable):
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
        self.dial_low_limit_travel = epics_signal_rw(float, prefix + ".DLLM")
        self.dial_high_limit_travel = epics_signal_rw(float, prefix + ".DHLM")
        self.offset_freeze_switch = epics_signal_rw(OffsetMode, prefix + ".FOFF")
        self.high_limit_switch = epics_signal_r(int, prefix + ".HLS")
        self.low_limit_switch = epics_signal_r(int, prefix + ".LLS")
        self.output_link = epics_signal_r(str, prefix + ".OUT")
        self.set_use_switch = epics_signal_rw(UseSetMode, prefix + ".SET")

        # Note:cannot use epics_signal_x here, as the motor record specifies that
        # we must write 1 to stop the motor. Simply processing the record is not
        # sufficient.
        # Put with completion will never complete as we are waiting for completion on
        # the move in set, so need to pass wait=False
        self.motor_stop = epics_signal_w(int, prefix + ".STOP", wait=False)

        # Currently requested fly info, stored in prepare
        self._fly_info: FlyMotorInfo | None = None

        # Set on kickoff(), complete when motor reaches self._fly_completed_position
        self._fly_status: WatchableAsyncStatus | None = None

        super().__init__(name)

    @cached_property
    def movable_logic(self) -> MotorMoveLogic:
        """Return MotorMoveLogic for this motor."""
        return MotorMoveLogic(
            readback=self.user_readback,
            setpoint=self.user_setpoint,
            motor_stop=self.motor_stop,
            low_limit_travel=self.low_limit_travel,
            high_limit_travel=self.high_limit_travel,
            motor_egu=self.motor_egu,
            dial_low_limit_travel=self.dial_low_limit_travel,
            dial_high_limit_travel=self.dial_high_limit_travel,
            velocity=self.velocity,
            acceleration_time=self.acceleration_time,
            precision=self.precision,
        )

    async def check_motor_limit(self, abs_start_pos: float, abs_end_pos: float):
        """Check the positions are within limits.

        Will raise a MotorLimitsException if the given absolute positions will be
        outside the motor soft limits.
        """
        await self.movable_logic.check_move(abs_start_pos, abs_end_pos)

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
            raise MotorLimitsError(
                f"Velocity {abs(value.velocity)} {egu}/s was requested for motor "
                f"{self.name} with max speed of {max_speed} {egu}/s."
            )

        acceleration_time = await self.acceleration_time.get_value()
        ramp_up_start_pos = value.ramp_up_start_pos(acceleration_time)
        ramp_down_end_pos = value.ramp_down_end_pos(acceleration_time)

        await self.check_motor_limit(ramp_up_start_pos, ramp_down_end_pos)

        # move to prepare position at maximum velocity
        await self.velocity.set(abs(max_speed))
        await self.set(ramp_up_start_pos)

        # Set velocity we will be using for the fly scan
        await self.velocity.set(abs(value.velocity))

    @AsyncStatus.wrap
    async def kickoff(self):
        """Begin moving motor from prepared position to final position."""
        fly_info = error_if_none(
            self._fly_info,
            f"Motor {self.name} must be prepared before attempting to kickoff.",
        )

        acceleration_time = await self.acceleration_time.get_value()
        self._fly_status = self.set(
            fly_info.ramp_down_end_pos(acceleration_time),
            timeout=fly_info.timeout,
        )

    def complete(self) -> WatchableAsyncStatus:
        """Mark as complete once motor reaches completed position."""
        fly_status = error_if_none(
            self._fly_status, f"kickoff for motor {self.name} not called."
        )
        return fly_status
