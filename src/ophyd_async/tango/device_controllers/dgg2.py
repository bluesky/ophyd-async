from __future__ import annotations

import asyncio
import time
from typing import Callable, List

from bluesky.protocols import Preparable, Triggerable

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import (
    TangoReadableDevice,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_x,
)
from tango import DevState


# --------------------------------------------------------------------
class DGG2Timer(TangoReadableDevice, Triggerable, Preparable):
    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self):
        self.sampletime = tango_signal_rw(
            float, self.trl + "/sampletime", device_proxy=self.proxy
        )
        self.remainingtime = tango_signal_rw(
            float, self.trl + "/remainingtime", device_proxy=self.proxy
        )

        self.set_readable_signals(
            read_uncached=[self.sampletime], config=[self.sampletime]
        )

        self.startandwaitfortimer = tango_signal_x(
            self.trl + "/startandwaitfortimer", device_proxy=self.proxy
        )

        self.start = tango_signal_x(self.trl + "/start", device_proxy=self.proxy)

        self._state = tango_signal_r(DevState, self.trl + "/state", self.proxy)

        self.set_name(self.name)

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
            await self.start.trigger()
        finally:
            if self.remainingtime.is_cachable():
                self.remainingtime.clear_sub(update_watchers)
            else:
                counter = 0
                state = await self._state.get_value()
                while state == DevState.MOVING:
                    # Update the watchers with the current position every 0.5 seconds
                    if counter % 5 == 0:
                        remaining_time = await self.remainingtime.get_value()
                        update_watchers(remaining_time)
                        counter = 0
                    await asyncio.sleep(0.1)
                    state = await self._state.get_value()
                    counter += 1

                # update_watchers(await self.remainingtime.get_value())
        if not self._set_success:
            raise RuntimeError("Timer was not triggered")

    # --------------------------------------------------------------------
    def trigger(self) -> AsyncStatus:
        watchers: List[Callable] = []
        return AsyncStatus(self._trigger(watchers), watchers)

    # --------------------------------------------------------------------
    def prepare(self, p_time) -> AsyncStatus:
        return self.sampletime.set(p_time)

    # --------------------------------------------------------------------
    async def set_time(self, s_time: float) -> None:
        await self.sampletime.set(s_time)
