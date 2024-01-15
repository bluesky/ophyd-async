
from __future__ import annotations

import asyncio
import time
from typing import List, Callable

from bluesky.protocols import Triggerable

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import TangoReadableDevice, tango_signal_rw, tango_signal_x


# --------------------------------------------------------------------
class DGG2Timer(TangoReadableDevice, Triggerable):

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self):

        self.sampletime = tango_signal_rw(float, self.trl + '/sampletime', device_proxy=self.proxy)
        self.remainingtime = tango_signal_rw(float, self.trl + '/remainingtime', device_proxy=self.proxy)

        self.set_readable_signals(read_uncached=[self.sampletime],
                                  config=[self.sampletime])

        self.startandwaitfortimer = tango_signal_x(self.trl+'/startandwaitfortimer', device_proxy=self.proxy)

    # --------------------------------------------------------------------
    async def _trigger(self, watchers: List[Callable] = []):
        self._set_success = True
        start = time.monotonic()
        total_time = await self.sampletime.get_value()

        def update_watchers(remaining_time: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=remaining_time,
                    initial=total_time,
                    target=total_time,
                    time_elapsed=time.monotonic() - start,
                )

        if self.remainingtime.is_cachable():
            self.remainingtime.subscribe_value(update_watchers)
        else:
            update_watchers(total_time)
        try:
            await self.startandwaitfortimer.trigger()
        finally:
            if self.remainingtime.is_cachable():
                self.remainingtime.clear_sub(update_watchers)
            else:
                update_watchers(await self.remainingtime.get_value())
        if not self._set_success:
            raise RuntimeError("Timer was not triggered")

    # --------------------------------------------------------------------
    def trigger(self) -> AsyncStatus:
        watchers: List[Callable] = []
        return AsyncStatus(self._trigger(watchers), watchers)

    # --------------------------------------------------------------------
    async def set_time(self, time: float) -> None:
        await self.sampletime.set(time)
