import asyncio
import time
from dataclasses import replace
from typing import Optional

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import StandardReadable, WatchableAsyncStatus
from ophyd_async.core.signal import observe_value
from ophyd_async.core.utils import WatcherUpdate

from ..signal.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class Motor(StandardReadable, Movable, Stoppable):
    """Device that moves a motor record"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.user_setpoint = epics_signal_rw(float, prefix + ".VAL")
        self.user_readback = epics_signal_r(float, prefix + ".RBV")
        self.velocity = epics_signal_rw(float, prefix + ".VELO")
        self.max_velocity = epics_signal_r(float, prefix + ".VMAX")
        self.acceleration_time = epics_signal_rw(float, prefix + ".ACCL")
        self.motor_egu = epics_signal_r(str, prefix + ".EGU")
        self.precision = epics_signal_r(int, prefix + ".PREC")
        self.deadband = epics_signal_r(float, prefix + ".RDBD")
        self.motor_done_move = epics_signal_r(float, prefix + ".DMOV")
        self.low_limit_travel = epics_signal_rw(int, prefix + ".LLM")
        self.high_limit_travel = epics_signal_rw(int, prefix + ".HLM")

        self.motor_stop = epics_signal_x(prefix + ".STOP")
        # Whether set() should complete successfully or not
        self._set_success = True
        # Set name and signals for read() and read_configuration()
        self.set_readable_signals(
            read=[self.user_readback],
            config=[self.velocity, self.motor_egu],
        )
        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)

    async def _move(self, new_position: float) -> WatcherUpdate[float]:
        self._set_success = True
        old_position, units, precision = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.motor_egu.get_value(),
            self.precision.get_value(),
        )
        await self.user_setpoint.set(new_position, wait=False)
        if not self._set_success:
            raise RuntimeError("Motor was stopped")
        return WatcherUpdate(
            initial=old_position,
            current=old_position,
            target=new_position,
            unit=units,
            precision=precision,
        )

    def move(self, new_position: float, timeout: Optional[float] = None):
        """Commandline only synchronous move of a Motor"""
        from bluesky.run_engine import call_in_bluesky_event_loop, in_bluesky_event_loop

        if in_bluesky_event_loop():
            raise RuntimeError("Will deadlock run engine if run in a plan")
        call_in_bluesky_event_loop(self._move(new_position), timeout)  # type: ignore

    @WatchableAsyncStatus.wrap
    async def set(self, new_position: float, timeout: float = 0.0):
        update = await self._move(new_position)
        start = time.monotonic()
        async for current_position in observe_value(self.user_readback):
            if not self._set_success:
                raise RuntimeError("Motor was stopped")
            yield replace(
                update,
                name=self.name,
                current=current_position,
                time_elapsed=time.monotonic() - start,
            )
            if await self.motor_done_move.get_value():
                return

    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self.motor_stop.trigger(wait=False)
        # Trigger any callbacks
        await self.user_readback._backend.put(await self.user_readback.get_value())
