import asyncio

from bluesky.protocols import (
    Flyable,
    Locatable,
    Location,
    Preparable,
    Stoppable,
)
from pydantic import BaseModel, Field

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    AsyncStatus,
    CalculatableTimeout,
    ConfigSignal,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
)
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class MotorLimitsException(Exception):
    pass


class InvalidFlyMotorException(Exception):
    pass


DEFAULT_MOTOR_FLY_TIMEOUT = 60
DEFAULT_WATCHER_UPDATE_FREQUENCY = 0.2


class FlyMotorInfo(BaseModel):
    """Minimal set of information required to fly a motor:"""

    #: Absolute position of the motor once it finishes accelerating to desired
    #: velocity, in motor EGUs
    start_position: float = Field(frozen=True)

    #: Absolute position of the motor once it begins decelerating from desired
    #: velocity, in EGUs
    end_position: float = Field(frozen=True)

    #: Time taken for the motor to get from start_position to end_position, excluding
    #: run-up and run-down, in seconds.
    time_for_move: float = Field(frozen=True, gt=0)

    #: Maximum time for the complete motor move, including run up and run down.
    #: Defaults to `time_for_move` + run up and run down times + 10s.
    timeout: CalculatableTimeout = Field(frozen=True, default=CALCULATE_TIMEOUT)


class Motor(StandardReadable, Locatable, Stoppable, Flyable, Preparable):
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

        # end_position of a fly move, with run_up_distance added on.
        self._fly_completed_position: float | None = None

        # Set on kickoff(), complete when motor reaches self._fly_completed_position
        self._fly_status: WatchableAsyncStatus | None = None

        # Set during prepare
        self._fly_timeout: CalculatableTimeout | None = CALCULATE_TIMEOUT

        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    @AsyncStatus.wrap
    async def prepare(self, value: FlyMotorInfo):
        """Calculate required velocity and run-up distance, then if motor limits aren't
        breached, move to start position minus run-up distance"""

        self._fly_timeout = value.timeout

        # Velocity, at which motor travels from start_position to end_position, in motor
        # egu/s.
        fly_velocity = await self._prepare_velocity(
            value.start_position,
            value.end_position,
            value.time_for_move,
        )

        # start_position with run_up_distance added on.
        fly_prepared_position = await self._prepare_motor_path(
            abs(fly_velocity), value.start_position, value.end_position
        )

        await self.set(fly_prepared_position)
        await self.velocity.set(abs(fly_velocity))

    @AsyncStatus.wrap
    async def kickoff(self):
        """Begin moving motor from prepared position to final position."""
        assert (
            self._fly_completed_position
        ), "Motor must be prepared before attempting to kickoff"

        self._fly_status = self.set(
            self._fly_completed_position, timeout=self._fly_timeout
        )

    def complete(self) -> WatchableAsyncStatus:
        """Mark as complete once motor reaches completed position."""
        assert self._fly_status, "kickoff not called"
        return self._fly_status

    @WatchableAsyncStatus.wrap
    async def set(self, value: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT):
        new_position = value
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
        # the move above, so need to pass wait=False
        await self.motor_stop.trigger(wait=False)

    async def _prepare_velocity(
        self, start_position: float, end_position: float, time_for_move: float
    ) -> float:
        fly_velocity = (end_position - start_position) / time_for_move
        max_speed, egu = await asyncio.gather(
            self.max_velocity.get_value(), self.motor_egu.get_value()
        )
        if abs(fly_velocity) > max_speed:
            raise MotorLimitsException(
                f"Motor speed of {abs(fly_velocity)} {egu}/s was requested for a motor "
                f" with max speed of {max_speed} {egu}/s"
            )
        # move to prepare position at maximum velocity
        await self.velocity.set(abs(max_speed))
        return fly_velocity

    async def locate(self) -> Location[float]:
        location: Location = {
            "setpoint": await self.user_setpoint.get_value(),
            "readback": await self.user_readback.get_value(),
        }
        return location

    async def _prepare_motor_path(
        self, fly_velocity: float, start_position: float, end_position: float
    ) -> float:
        # Distance required for motor to accelerate from stationary to fly_velocity, and
        # distance required for motor to decelerate from fly_velocity to stationary
        run_up_distance = (
            (await self.acceleration_time.get_value()) * fly_velocity * 0.5
        )

        self._fly_completed_position = end_position + run_up_distance

        # Prepared position not used after prepare, so no need to store in self
        fly_prepared_position = start_position - run_up_distance

        motor_lower_limit, motor_upper_limit, egu = await asyncio.gather(
            self.low_limit_travel.get_value(),
            self.high_limit_travel.get_value(),
            self.motor_egu.get_value(),
        )

        if (
            not motor_upper_limit >= fly_prepared_position >= motor_lower_limit
            or not motor_upper_limit
            >= self._fly_completed_position
            >= motor_lower_limit
        ):
            raise MotorLimitsException(
                f"Motor trajectory for requested fly is from "
                f"{fly_prepared_position}{egu} to "
                f"{self._fly_completed_position}{egu} but motor limits are "
                f"{motor_lower_limit}{egu} <= x <= {motor_upper_limit}{egu} "
            )
        return fly_prepared_position
