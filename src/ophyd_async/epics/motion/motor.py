import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import AsyncStatus, StandardReadable

from ..signal.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class Motor(StandardReadable, Movable, Stoppable):
    """Device that moves a motor record"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.user_setpoint = epics_signal_rw(float, prefix + ".VAL")
        self.user_readback = epics_signal_r(float, prefix + ".RBV")
        self.velocity = epics_signal_rw(float, prefix + ".VELO")
        self.max_velocity = epics_signal_r(float, prefix + ".VMAX")
        self.acceleration = epics_signal_rw(float, prefix + ".ACCL")
        self.motor_egu = epics_signal_r(str, prefix + ".EGU")
        self.precision = epics_signal_r(int, prefix + ".PREC")
        self.motor_resolution = epics_signal_r(float, prefix + ".MRES")
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

    async def _move(self, new_position: float, watchers: List[Callable] = []):
        self._set_success = True
        start = time.monotonic()
        old_position, units, precision = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.motor_egu.get_value(),
            self.precision.get_value(),
        )

        def update_watchers(current_position: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    unit=units,
                    precision=precision,
                    time_elapsed=time.monotonic() - start,
                )

        self.user_readback.subscribe_value(update_watchers)
        try:
            await self.user_setpoint.set(new_position)
        finally:
            self.user_readback.clear_sub(update_watchers)
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    def move(self, new_position: float, timeout: Optional[float] = None):
        """Commandline only synchronous move of a Motor"""
        from bluesky.run_engine import call_in_bluesky_event_loop, in_bluesky_event_loop

        if in_bluesky_event_loop():
            raise RuntimeError("Will deadlock run engine if run in a plan")
        call_in_bluesky_event_loop(self._move(new_position), timeout)  # type: ignore

    def set(self, new_position: float, timeout: Optional[float] = None) -> AsyncStatus:
        watchers: List[Callable] = []
        coro = asyncio.wait_for(self._move(new_position, watchers), timeout=timeout)
        return AsyncStatus(coro, watchers)

    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        status = self.motor_stop.trigger(wait=False)
        await status
