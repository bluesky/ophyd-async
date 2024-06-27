from __future__ import annotations

from typing import Dict, Optional

from bluesky.protocols import Reading, Triggerable

from ophyd_async.core import (
    AsyncStatus,
    ConfigSignal,
    HintedSignal,
)
from ophyd_async.tango import TangoReadableDevice, tango_signal_rw, tango_signal_x


# --------------------------------------------------------------------
class SIS3820Counter(TangoReadableDevice, Triggerable):

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name: str = "", sources: dict = None) -> None:
        if sources is None:
            sources = {}
        self.src_dict["counts"] = sources.get("counts", "/Counts")
        self.src_dict["offset"] = sources.get("offset", "/Offset")
        self.src_dict["reset"] = sources.get("reset", "/Reset")

        for key in self.src_dict:
            if not self.src_dict[key].startswith("/"):
                self.src_dict[key] = "/" + self.src_dict[key]
        
        self.trl = trl

        with self.add_children_as_readables(HintedSignal):
            self.counts = tango_signal_rw(
                float, self.trl + self.src_dict["counts"], device_proxy=self.proxy
            )
        with self.add_children_as_readables(ConfigSignal):
            self.offset = tango_signal_rw(
                float, self.trl + self.src_dict["offset"], device_proxy=self.proxy
            )

        self.reset = tango_signal_x(
            self.trl + self.src_dict["reset"], device_proxy=self.proxy
        )

        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    async def read(self) -> Dict[str, Reading]:
        ret = await super().read()
        return ret

    def trigger(self) -> AsyncStatus:
        return AsyncStatus(self._trigger())

    async def _trigger(self) -> None:
        await self.reset.trigger()
