from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Locatable, Location, Stoppable
from tango import DevState

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import (
    TangoReadableDevice,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_x,
)


# --------------------------------------------------------------------
class OmsVME58Motor(TangoReadableDevice, Locatable, Stoppable):

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self):

        self.position = tango_signal_rw(
            float, self.trl + "/position", device_proxy=self.proxy
        )
        self.baserate = tango_signal_rw(
            int, self.trl + "/baserate", device_proxy=self.proxy
        )
        self.slewrate = tango_signal_rw(
            int, self.trl + "/slewrate", device_proxy=self.proxy
        )
        self.conversion = tango_signal_rw(
            float, self.trl + "/conversion", device_proxy=self.proxy
        )
        self.acceleration = tango_signal_rw(
            int, self.trl + "/acceleration", device_proxy=self.proxy
        )

        self.set_readable_signals(
            read_uncached=[self.position],
            config=[self.baserate, self.slewrate, self.conversion, self.acceleration],
        )

        self._stop = tango_signal_x(self.trl + "/stopmove", self.proxy)
        self._state = tango_signal_r(DevState, self.trl + "/state", self.proxy)

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

        if self.position.is_cachable():
            self.position.subscribe_value(update_watchers)
        else:
            update_watchers(start_position)
        try:
            await self.position.set(new_position)
            await asyncio.sleep(0.1)
            while await self._state.get_value() == DevState.MOVING:
                await asyncio.sleep(0.1)
        finally:
            if self.position.is_cachable():
                self.position.clear_sub(update_watchers)
            else:
                update_watchers(await self.position.get_value())
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    # --------------------------------------------------------------------
    def set(self, new_position: float, timeout: Optional[float] = None) -> AsyncStatus:
        watchers: List[Callable] = []
        coro = asyncio.wait_for(self._move(new_position, watchers), timeout=timeout)
        return AsyncStatus(coro, watchers)

    # --------------------------------------------------------------------
    async def locate(self) -> Location:
        set_point = await self.position.get_setpoint()
        readback = await self.position.get_value()
        return Location(setpoint=set_point, readback=readback)

    # --------------------------------------------------------------------
    async def stop(self, success=False):
        self._set_success = success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self._stop.trigger()
