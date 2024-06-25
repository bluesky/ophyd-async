from __future__ import annotations

from typing import Dict

from bluesky.protocols import Reading, Triggerable

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import TangoReadableDevice, tango_signal_rw, tango_signal_x


# --------------------------------------------------------------------
class SIS3820Counter(TangoReadableDevice, Triggerable):
    src_dict: dict = {
        "counts": "/counts",
        "offset": "/offset",
        "reset": "/reset",
    }
    trl: str
    name: str

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name: str = "", sources: dict = None) -> None:
        if sources is None:
            sources = {}
        self.src_dict["counts"] = sources.get("counts", "/counts")
        self.src_dict["offset"] = sources.get("offset", "/offset")
        self.src_dict["reset"] = sources.get("reset", "/reset")

        for key in self.src_dict:
            if not self.src_dict[key].startswith("/"):
                self.src_dict[key] = "/" + self.src_dict[key]

        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self) -> None:
        self.counts = tango_signal_rw(
            float, self.trl + self.src_dict["counts"], device_proxy=self.proxy
        )
        self.offset = tango_signal_rw(
            float, self.trl + self.src_dict["offset"], device_proxy=self.proxy
        )

        self.set_readable_signals(read_uncached=[self.counts], config=[self.offset])

        self.reset = tango_signal_x(
            self.trl + self.src_dict["reset"], device_proxy=self.proxy
        )

        self.set_name(self.name)

    async def read(self) -> Dict[str, Reading]:
        ret = await super().read()
        return ret

    def trigger(self) -> AsyncStatus:
        return AsyncStatus(self._trigger())

    async def _trigger(self) -> None:
        await self.reset.trigger()
