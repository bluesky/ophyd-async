
from __future__ import annotations

from typing import Dict

# from bluesky.protocols import Triggerable
from bluesky.protocols import Reading

from ophyd_async.tango import TangoReadableDevice, tango_signal_rw, tango_signal_x


# --------------------------------------------------------------------
class SIS3820Counter(TangoReadableDevice):  # Triggerable

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def register_signals(self):

        self.counts = tango_signal_rw(float, self.trl + '/counts', device_proxy=self.proxy)
        self.offset = tango_signal_rw(float, self.trl + '/offset', device_proxy=self.proxy)

        self.set_readable_signals(read_uncached=[self.counts],
                                  config=[self.offset])

        self.reset = tango_signal_x(self.trl + '/reset', device_proxy=self.proxy)

    # --------------------------------------------------------------------
    # Theoretically counter has to be reset before triggering, but I do not how to do it
    # def trigger(self) -> AsyncStatus:
    #     return self.reset.trigger()

    # --------------------------------------------------------------------
    async def read(self) -> Dict[str, Reading]:
        ret = await super().read()
        await self.reset.trigger()
        return ret
