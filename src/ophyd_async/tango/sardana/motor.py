
from __future__ import annotations

import asyncio
import time

from typing import Optional, List, Callable

from bluesky.protocols import Locatable, Stoppable, Location

from tango import DevState

from ophyd_async.tango import TangoReadableDevice, tango_signal_x, tango_signal_r, tango_signal_rw, tango_signal_w
from ophyd_async.core import AsyncStatus, Signal


# --------------------------------------------------------------------
class SardanaMotor(TangoReadableDevice, Locatable, Stoppable):

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self):

        self.position = tango_signal_rw(float, self.trl + '/Position', device_proxy=self.proxy)
        self.baserate = tango_signal_rw(float, self.trl + '/Base_rate', device_proxy=self.proxy)
        self.velocity = tango_signal_rw(float, self.trl + '/Velocity', device_proxy=self.proxy)
        self.acceleration = tango_signal_rw(float, self.trl + '/Acceleration', device_proxy=self.proxy)
        self.deceleration = tango_signal_rw(float, self.trl + '/Deceleration', device_proxy=self.proxy)

        self.set_readable_signals(read_uncached=[self.position],
                                  config=[self.baserate,
                                          self.velocity,
                                          self.acceleration,
                                          self.deceleration])

        self._stop = tango_signal_x(self.trl + '/Stop', self.proxy)
        self._state = tango_signal_r(DevState, self.trl + '/State', self.proxy)

    # --------------------------------------------------------------------
    async def _move(self, new_position: float, watchers: List[Callable] = []):
        self._set_success = True
        start = time.monotonic()
        start_position = await self.position.get_value()

        def update_watchers(current_position: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=current_position,
                    initial=start_position,
                    target=new_position,
                    time_elapsed=time.monotonic() - start,
                )

        # raise RuntimeError("Test")
        self.position.subscribe_value(update_watchers)
        try:
            await self.position.set(new_position)
            await asyncio.sleep(0.1)
            while await self._state.get_value() == DevState.MOVING:
                await asyncio.sleep(0.1)
        finally:
            self.position.clear_sub(update_watchers)
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    # --------------------------------------------------------------------
    def set(self, new_position: float, timeout: Optional[float] = None) -> AsyncStatus:
        watchers: List[Callable] = []
        coro = asyncio.wait_for(self._move(new_position, watchers), timeout=timeout)
        return AsyncStatus(coro, watchers)

    # --------------------------------------------------------------------
    async def locate(self) -> Location:
        pass

    # --------------------------------------------------------------------
    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self._stop.execute(wait=False)

