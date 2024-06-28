import asyncio

from bluesky.protocols import Flyable, Movable, Preparable, Stoppable
from pydantic import BaseModel

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
        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    def prepare(self, value: FlyMotorInfo):
        """Calculate required velocity and run-up distance, then if motor limits aren't
        breached, move to start position minus run-up distance"""
        return AsyncStatus(self._prepare(value))

    def kickoff(self): ...

    def complete(self): ...

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

    async def _prepare(self, value: FlyMotorInfo) -> None:
        # Velocity at which motor travels from start_position to end_position, in mm/s
        self.fly_velocity = abs(
            (value.start_position - value.end_position) / value.time_for_move
        )
        velocity_max = await self.max_velocity.get_value()
        if self.fly_velocity > velocity_max:
            raise MotorLimitsException(
                f"Velocity of {self.fly_velocity}mm/s was requested for a motor with "
                f"vmax of {velocity_max}mm/s"
            )
        await self.velocity.set(self.fly_velocity)

        # Distance required for motor to accelerate to fly_velocity before reaching
        # start_position, and distance required for motor to decelerate from
        # fly_velocity to zero after end_position
        self.run_up_distance = (
            0.5 * (await self.acceleration_time.get_value()) * self.fly_velocity
        )
        motor_lower_limit = await self.low_limit_travel.get_value()
        motor_upper_limit = await self.high_limit_travel.get_value()
        if (
            value.start_position - self.run_up_distance < motor_lower_limit
            or value.end_position + self.run_up_distance > motor_upper_limit
        ):
            raise MotorLimitsException(
                f"Requested a motor trajectory of {value.start_position}mm to "
                f"{value.end_position}mm and motor limits are {value.start_position} "
                f"<= x <= {value.end_position} "
            )

        await self.user_setpoint.set(value.start_position - self.run_up_distance)
        return await self.set(value.start_position - self.run_up_distance)
