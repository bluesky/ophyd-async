import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Movable, Stoppable

from ophyd.v2.core import AsyncStatus, StandardReadable
from ophyd.v2.epics import EpicsSignalR, EpicsSignalRW, EpicsSignalX


class Motor(StandardReadable, Movable, Stoppable):
    """Device that moves a motor record"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.setpoint = EpicsSignalRW(float, ".VAL")
        self.readback = EpicsSignalR(float, ".RBV")
        self.velocity = EpicsSignalRW(float, ".VELO")
        self.units = EpicsSignalR(str, ".EGU")
        self.precision = EpicsSignalR(int, ".PREC")
        # Signals that collide with standard methods should have a trailing underscore
        self.stop_ = EpicsSignalX(".STOP", write_value=1, wait=False)
        # Whether set() should complete successfully or not
        self._set_success = True
        # Set prefix, name, and signals for read() and read_configuration()
        super().__init__(
            prefix=prefix,
            name=name,
            primary=self.readback,
            config=[self.velocity, self.units],
        )

    async def _move(self, new_position: float, watchers: List[Callable] = []):
        self._set_success = True
        start = time.time()
        old_position, units, precision = await asyncio.gather(
            self.setpoint.get_value(),
            self.units.get_value(),
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
                    time_elapsed=time.time() - start,
                )

        self.readback.subscribe_value(update_watchers)
        try:
            await self.setpoint.set(new_position)
        finally:
            self.readback.clear_sub(update_watchers)
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
        await self.stop_.execute()
