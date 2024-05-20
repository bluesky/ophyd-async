import asyncio

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    ConfigSignal,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
)
from ophyd_async.core.signal import observe_value
from ophyd_async.core.utils import DEFAULT_TIMEOUT, WatcherUpdate

from ..signal.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class Motor(StandardReadable, Movable, Stoppable):
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

    @WatchableAsyncStatus.wrap
    async def set(self, new_position: float, timeout: float | None = None):
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
        if timeout is None:
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
        # Trigger any callbacks
        await self.user_readback._backend.put(await self.user_readback.get_value())
