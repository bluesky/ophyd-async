import asyncio
from dataclasses import replace

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    AsyncStatus,
    ConfigSignal,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
)
from ophyd_async.core.signal import observe_value
from ophyd_async.core.utils import WatcherUpdate

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

    async def _move(
        self, new_position: float
    ) -> tuple[WatcherUpdate[float], AsyncStatus]:
        self._set_success = True
        old_position, units, precision = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.motor_egu.get_value(),
            self.precision.get_value(),
        )
        move_status = self.user_setpoint.set(new_position, wait=True)
        if not self._set_success:
            raise RuntimeError("Motor was stopped")
        return (
            WatcherUpdate(
                initial=old_position,
                current=old_position,
                target=new_position,
                unit=units,
                precision=precision,
            ),
            move_status,
        )

    @WatchableAsyncStatus.wrap
    async def set(self, new_position: float, timeout: float | None = None):
        update, move_status = await self._move(new_position)
        async for current_position in observe_value(
            self.user_readback, done_status=move_status
        ):
            if not self._set_success:
                raise RuntimeError("Motor was stopped")
            yield replace(
                update,
                name=self.name,
                current=current_position,
            )

    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self.motor_stop.trigger(wait=False)
        # Trigger any callbacks
        await self.user_readback._backend.put(await self.user_readback.get_value())
