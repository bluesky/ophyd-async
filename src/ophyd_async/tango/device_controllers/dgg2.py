from __future__ import annotations

import asyncio
from asyncio import Event
from typing import Optional

from bluesky.protocols import Preparable, Triggerable

from ophyd_async.core import (
    AsyncStatus,
    ConfigSignal,
    HintedSignal,
)
from ophyd_async.core.utils import DEFAULT_TIMEOUT
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
    def __init__(self, trl: str, name="", sources: dict = None) -> None:
        if sources is None:
            sources = {}
        self.trl = trl
        self.src_dict["sampletime"] = sources.get("sampletime", "/SampleTime")
        self.src_dict["remainingtime"] = sources.get("remainingtime", "/RemainingTime")
        self.src_dict["startandwaitfortimer"] = sources.get(
            "startandwaitfortimer", "/StartAndWaitForTimer"
        )
        self.src_dict["start"] = sources.get("start", "/Start")
        self.src_dict["state"] = sources.get("state", "/State")

        for key in self.src_dict:
            if not self.src_dict[key].startswith("/"):
                self.src_dict[key] = "/" + self.src_dict[key]

        # Add sampletime as an unchached hinted signal
        with self.add_children_as_readables(ConfigSignal):
            self.sampletime = tango_signal_rw(
                float, self.trl + self.src_dict["sampletime"], device_proxy=self.proxy
            )

        with self.add_children_as_readables(HintedSignal):
            self.remainingtime = tango_signal_rw(
                float,
                self.trl + self.src_dict["remainingtime"],
                device_proxy=self.proxy,
            )

        self.startandwaitfortimer = tango_signal_x(
            self.trl + self.src_dict["startandwaitfortimer"], device_proxy=self.proxy
        )

        self.start = tango_signal_x(
            self.trl + self.src_dict["start"], device_proxy=self.proxy
        )

        self._state = tango_signal_r(
            DevState, self.trl + self.src_dict["state"], self.proxy
        )

        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    def prepare(self, p_time: float) -> AsyncStatus:
        return self.sampletime.set(p_time)

    def trigger(self):
        return AsyncStatus(self._trigger())

    async def _trigger(self):
        sample_time = await self.sampletime.get_value()
        timeout = sample_time + DEFAULT_TIMEOUT
        await self.start.trigger(wait=True, timeout=timeout)
        await self._wait()

    async def _wait(self, event: Optional[Event] = None) -> None:
        # await asyncio.sleep(0.5)
        state = await self._state.get_value()
        try:
            while state == DevState.MOVING:
                await asyncio.sleep(0.1)
                state = await self._state.get_value()
        except Exception as e:
            raise RuntimeError(f"Error waiting for motor to stop: {e}")
        finally:
            if event:
                event.set()
            if state != DevState.ON:
                raise RuntimeError(f"Motor did not stop correctly. State {state}")
