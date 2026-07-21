"""Support for EPICS motor record.

https://github.com/epics-modules/motor
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import cached_property

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DeviceMock,
    FlyableLogic,
    FlyMotorInfo,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalW,
    StandardFlyable,
    StandardMovable,
    StandardReadable,
    StrictEnum,
    TimeoutCalculator,
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
class MotorFlyCtx:
    """State threaded through a motor fly scan (prepare -> kickoff -> complete)."""

    #: The info the scan was prepared with, produced by `on_prepare`.
    fly_info: FlyMotorInfo
    #: The move to the end position, produced by `on_kickoff`.
    status: AsyncStatus | None = None


@dataclass
class MotorFlyableMovableLogic(
    MovableLogic[float], FlyableLogic[FlyMotorInfo, MotorFlyCtx]
):
    """Combined move + fly logic for a motor record.

    A single logic object backs a `Motor`'s `movable_logic` and `flyable_logic`:
    it implements `MovableLogic` (the motor-record move, limit and timeout logic)
    and `FlyableLogic` (the fly hooks, which reuse `move`/`check_move` and carry
    all per-scan state in a `MotorFlyCtx` rather than on the logic).
    """

    motor_stop: SignalW[int]
    low_limit_travel: SignalRW[float]
    high_limit_travel: SignalRW[float]
    dial_low_limit_travel: SignalRW[float]
    dial_high_limit_travel: SignalRW[float]
    velocity: SignalRW[float]
    acceleration_time: SignalRW[float]
    motor_done_move: SignalR[int]
    max_velocity: SignalR[float]
    motor_egu: SignalR[str]

    async def stop(self):
        """Request to stop moving, but only if the motor is currently moving.

        This makes stop idempotent when the motor is already stopped, so a motor
        that is both moved and staged in a run (e.g. `bp.scan`) is not stopped
        twice -- once by the RunEngine (it stops everything it set) and once by
        `unstage`.
        """
        if not await self.motor_done_move.get_value():
            await self.motor_stop.set(1)

    async def check_move(self, new_position: float):
        """Check the positions are within limits.

        Will raise a MotorLimitsException if the given absolute positions will be
        outside the motor soft limits.
        """
        (
            motor_lower_limit,
            motor_upper_limit,
            (units, _),
            dial_lower_limit,
            dial_upper_limit,
        ) = await asyncio.gather(
            self.low_limit_travel.get_value(),
            self.high_limit_travel.get_value(),
            self.get_units_precision(),
            self.dial_low_limit_travel.get_value(),
            self.dial_high_limit_travel.get_value(),
        )

        # EPICS motor record treats dial limits of 0, 0 as no limit
        # Use DLLM and DHLM to check
        if dial_lower_limit == 0 and dial_upper_limit == 0:
            return

        old_position = await self.readback.get_value()
        # Use real motor limit(i.e. HLM and LLM) to check if the move is permissible
        if (
            not motor_upper_limit >= old_position >= motor_lower_limit
            or not motor_upper_limit >= new_position >= motor_lower_limit
        ):
            name = self.readback.name
            raise MotorLimitsError(
                f"{name} motor trajectory for requested fly/move is from "
                f"{old_position}{units} to "
                f"{new_position}{units} but motor limits are "
                f"{motor_lower_limit}{units} <= x <= {motor_upper_limit}{units} "
                f"dial limits are "
                f"{dial_lower_limit}{units} <= x <= {dial_upper_limit}."
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

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        """Move by setting the setpoint and waiting for put completion."""
        await self.setpoint.set(new_position, timeout=timeout())

    async def on_prepare(self, value: FlyMotorInfo) -> MotorFlyCtx:
        """Move to the beginning of a run-up distance ready for a fly scan."""
        # Velocity at which the motor travels from start to end, in motor egu/s.
        max_speed, egu = await asyncio.gather(
            self.max_velocity.get_value(), self.motor_egu.get_value()
        )
        if value.speed > max_speed:
            raise MotorLimitsError(
                f"Speed {value.speed} {egu}/s was requested for motor "
                f"{self.readback.name} with max speed of {max_speed} {egu}/s."
            )
        # Check the run-up and run-down positions are within limits
        acceleration_time = await self.acceleration_time.get_value()
        ramp_up_start_pos = value.ramp_up_start_pos(acceleration_time)
        ramp_down_end_pos = value.ramp_down_end_pos(acceleration_time)
        await asyncio.gather(
            self.check_move(ramp_up_start_pos), self.check_move(ramp_down_end_pos)
        )
        # Move to the run-up start at maximum velocity
        await self.velocity.set(abs(max_speed))
        old_position = await self.readback.get_value()
        timeout = await self.calculate_timeout(old_position, ramp_up_start_pos)
        await self.move(ramp_up_start_pos, lambda: timeout)
        # Set the velocity we will use for the fly scan
        await self.velocity.set(value.speed)
        return MotorFlyCtx(fly_info=value)

    async def on_kickoff(self, ctx: MotorFlyCtx) -> MotorFlyCtx:
        """Begin moving the motor from the prepared position to the final position."""
        acceleration_time = await self.acceleration_time.get_value()
        target = ctx.fly_info.ramp_down_end_pos(acceleration_time)
        if ctx.fly_info.timeout == CALCULATE_TIMEOUT:
            initial = await self.readback.get_value()
            timeout = await self.calculate_timeout(initial, target)
        else:
            timeout = ctx.fly_info.timeout
        ctx.status = AsyncStatus(self.move(target, lambda: timeout))
        # Wait out the run-up so the motor is at constant velocity before
        # kickoff() returns. A plan can then kickoff the motor and afterwards
        # kickoff internally-triggered detectors, which is more accurate for
        # long acceleration times.
        await asyncio.sleep(acceleration_time)
        return ctx

    async def on_complete(self, ctx: MotorFlyCtx) -> None:
        """Block until the motor reaches the fly-scan end position."""
        status = error_if_none(
            ctx.status, f"kickoff for motor {self.readback.name} not called."
        )
        await status


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
class Motor(
    StandardMovable[float], StandardFlyable[FlyMotorInfo, MotorFlyCtx], StandardReadable
):
    """Device that moves a motor record."""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.motor_egu = epics_signal_r(str, prefix + ".EGU")
            self.motor_resolution = epics_signal_r(float, prefix + ".MRES")
            self.steps_per_revolution = epics_signal_r(int, prefix + ".SREV")
            self.units_per_revolution = epics_signal_r(float, prefix + ".UREV")
            self.encoder_resolution = epics_signal_r(float, prefix + ".ERES")
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

        super().__init__(name)

    @cached_property
    def _logic(self) -> MotorFlyableMovableLogic:
        """The combined move + fly logic, shared by movable_logic and flyable_logic."""
        return MotorFlyableMovableLogic(
            readback=self.user_readback,
            setpoint=self.user_setpoint,
            motor_stop=self.motor_stop,
            low_limit_travel=self.low_limit_travel,
            high_limit_travel=self.high_limit_travel,
            dial_low_limit_travel=self.dial_low_limit_travel,
            dial_high_limit_travel=self.dial_high_limit_travel,
            velocity=self.velocity,
            acceleration_time=self.acceleration_time,
            motor_done_move=self.motor_done_move,
            max_velocity=self.max_velocity,
            motor_egu=self.motor_egu,
        )

    @cached_property
    def movable_logic(self) -> MotorFlyableMovableLogic:
        return self._logic

    @cached_property
    def flyable_logic(self) -> MotorFlyableMovableLogic:
        return self._logic
