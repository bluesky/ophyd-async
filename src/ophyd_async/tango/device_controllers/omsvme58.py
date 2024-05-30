from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Locatable, Location, Stoppable

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import (
    TangoReadableDevice,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_x,
)
from tango import DevState


# --------------------------------------------------------------------
class OmsVME58Motor(TangoReadableDevice, Locatable, Stoppable):
    trl: str
    name: str
    src_dict: dict = {
        "position": "/position",
        "baserate": "/baserate",
        "slewrate": "/slewrate",
        "conversion": "/conversion",
        "acceleration": "/acceleration",
        "stop": "/stopmove",
        "state": "/state",
    }

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name: str = "", sources: dict = None) -> None:
        if sources is None:
            sources = {}
        self.src_dict["position"] = sources.get("position", "/position")
        self.src_dict["baserate"] = sources.get("baserate", "/baserate")
        self.src_dict["slewrate"] = sources.get("slewrate", "/slewrate")
        self.src_dict["conversion"] = sources.get("conversion", "/conversion")
        self.src_dict["acceleration"] = sources.get("acceleration", "/acceleration")
        self.src_dict["stop"] = sources.get("stop", "/stopmove")
        self.src_dict["state"] = sources.get("state", "/state")

        for key in self.src_dict:
            if not self.src_dict[key].startswith("/"):
                self.src_dict[key] = "/" + self.src_dict[key]

        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self) -> None:
        self.position = tango_signal_rw(
            float, self.trl + self.src_dict["position"], device_proxy=self.proxy
        )
        self.baserate = tango_signal_rw(
            int, self.trl + self.src_dict["baserate"], device_proxy=self.proxy
        )
        self.slewrate = tango_signal_rw(
            int, self.trl + self.src_dict["slewrate"], device_proxy=self.proxy
        )
        self.conversion = tango_signal_rw(
            float, self.trl + self.src_dict["conversion"], device_proxy=self.proxy
        )
        self.acceleration = tango_signal_rw(
            int, self.trl + self.src_dict["acceleration"], device_proxy=self.proxy
        )

        self.set_readable_signals(
            read_uncached=[self.position],
            config=[self.baserate, self.slewrate, self.conversion, self.acceleration],
        )

        self._stop = tango_signal_x(self.trl + self.src_dict["stop"], self.proxy)
        self._state = tango_signal_r(
            DevState, self.trl + self.src_dict["state"], self.proxy
        )

        self.set_name(self.name)

    # --------------------------------------------------------------------
    async def _move(
        self, new_position: float, watchers: List[Callable] or None = None
    ) -> None:
        if watchers is None:
            watchers = []
        self._set_success = True
        start = time.monotonic()
        start_position = await self.position.get_value()

        def update_watchers(current_position: float) -> None:
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
            counter = 0
            state = await self._state.get_value()
            while state == DevState.MOVING:
                # Update the watchers with the current position every 0.5 seconds
                if counter % 5 == 0:
                    current_position = await self.position.get_value()
                    update_watchers(current_position)
                    counter = 0
                await asyncio.sleep(0.1)
                state = await self._state.get_value()
                counter += 1
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
    def stop(self, success: bool = False) -> AsyncStatus:
        self._set_success = success
        return self._stop.trigger()
