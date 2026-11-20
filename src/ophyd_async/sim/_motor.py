import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import cached_property

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    KICKED_OFF,
    AsyncStatus,
    DeviceMock,
    FlyableLogic,
    FlyMotorInfo,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalW,
    SoftSignalBackend,
    StandardFlyable,
    StandardMovable,
    StandardReadable,
    TimeoutCalculator,
    WatcherUpdate,
    default_mock_class,
    soft_signal_r_and_setter,
    soft_signal_rw,
    wait_for_value,
    watch_readback,
)
from ophyd_async.core import StandardReadableFormat as Format

from ._motor_hardware import SimMotorHardware


@dataclass(frozen=True)
class SimMotorPrepareCtx:
    """What a simulated motor fly scan needs after `prepare_to_fly`."""

    #: Where to start from: the start position with the run-up distance added.
    start: float
    #: Where to end: the end position with the run-down distance added.
    end: float
    #: How long the motor takes to get up to speed.
    acceleration_time: float


@dataclass
class SimMotorLogic(
    MovableLogic[float], FlyableLogic[FlyMotorInfo, SimMotorPrepareCtx]
):
    """Combined move + fly logic for a simulated motor."""

    motor_stop: SignalW[int]
    motor_done_move: SignalR[int]
    velocity: SignalRW[float]
    acceleration_time: SignalRW[float]

    async def ensure_stopped(self) -> None:
        """Stop the motor, a fly included, and wait until it is done moving."""
        await self.motor_stop.set(1)
        timeout = await self.acceleration_time.get_value() + DEFAULT_TIMEOUT
        await wait_for_value(self.motor_done_move, 1, timeout=timeout)

    async def move(self, new_position: float, timeout: TimeoutCalculator) -> None:
        """Move by setting the setpoint and waiting for put completion.

        The put completes early if the motor is stopped.
        """
        await self.setpoint.set(new_position, timeout=timeout())

    async def prepare_to_fly(
        self, name: str, value: FlyMotorInfo, previous_ctx: SimMotorPrepareCtx | None
    ) -> AsyncGenerator[SimMotorPrepareCtx | WatcherUpdate, None]:
        """Work out the run-up and run-down positions, then move to the run-up start.

        Progress of the move is reported.
        """
        acceleration_time = await self.acceleration_time.get_value()
        ctx = SimMotorPrepareCtx(
            start=value.ramp_up_start_pos(acceleration_time),
            end=value.ramp_down_end_pos(acceleration_time),
            acceleration_time=acceleration_time,
        )
        yield ctx
        # Move to start as fast as we can
        await self.velocity.set(0)
        old_position = await self.readback.get_value()
        async with AsyncStatus(self.move(ctx.start, lambda: None)) as status:
            async for update in watch_readback(
                self, status, target=ctx.start, initial=old_position
            ):
                yield update
        # Set the velocity for the actual move
        await self.velocity.set(value.speed)

    async def fly(
        self, ctx: SimMotorPrepareCtx
    ) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        """Move from the run-up start to the run-down end, reporting progress.

        Kicked off once the run-up is done and the motor is at constant velocity.
        """
        async with AsyncStatus(self.move(ctx.end, lambda: None)) as status:
            await asyncio.sleep(ctx.acceleration_time)
            yield KICKED_OFF
            async for update in watch_readback(
                self, status, target=ctx.end, initial=ctx.start
            ):
                yield update


# Remove InstantMovableMock as SimMotor owns this logic, depends if instant=True/False
@default_mock_class(DeviceMock)
class SimMotor(
    StandardReadable,
    StandardMovable[float],
    StandardFlyable[FlyMotorInfo, SimMotorPrepareCtx],
):
    """For usage when simulating a motor.

    `stage()` calls the logic's `ensure_ready`, which calls `ensure_stopped` and so
    stops the simulated motion and sets the setpoint to the current readback.
    `unstage()` cancels a fly in progress, then calls `ensure_stopped` too.
    """

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
        velocity = 0 if instant else 1.0
        acceleration_time = 0.5
        setpoint_backend = SoftSignalBackend(
            float,
            initial_value,
            units=units,
            setter=lambda target: self._hardware.move(target),
        )
        self.motor_done_move, self._set_done_move = soft_signal_r_and_setter(int, 1)
        self._hardware = SimMotorHardware(
            position=initial_value,
            set_readback=self._user_readback_set,
            set_setpoint=setpoint_backend.set_value,
            set_done_move=self._set_done_move,
            velocity=velocity,
            acceleration_time=acceleration_time,
        )
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.velocity = soft_signal_rw(
                float, velocity, setter=self._hardware.set_velocity
            )
            self.acceleration_time = soft_signal_rw(
                float,
                acceleration_time,
                setter=self._hardware.set_acceleration_time,
            )
        self.user_setpoint = SignalRW(backend=setpoint_backend)
        self.motor_stop = soft_signal_rw(int, setter=lambda _: self._hardware.stop())
        super().__init__(name=name)

    @cached_property
    def logic(self) -> SimMotorLogic:
        return SimMotorLogic(
            readback=self.user_readback,
            motor_stop=self.motor_stop,
            motor_done_move=self.motor_done_move,
            setpoint=self.user_setpoint,
            velocity=self.velocity,
            acceleration_time=self.acceleration_time,
        )
