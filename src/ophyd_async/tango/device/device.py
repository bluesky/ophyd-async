"""Default Tango Devices"""

from __future__ import annotations

from abc import abstractmethod
from typing import Union, Tuple, Sequence

from tango.asyncio import DeviceProxy

from ophyd_async.core import StandardReadable

__all__ = ("TangoReadableDevice", )


# --------------------------------------------------------------------
class TangoReadableDevice(StandardReadable):
    """
    General class for TangoDevices

    Usage: to proper signals mount should be awaited:

    new_device = await TangoDevice(<tango_device>)
    """

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        self.trl = trl
        self.proxy: DeviceProxy = None
        StandardReadable.__init__(self, name=name)

    # --------------------------------------------------------------------
    def __await__(self):
        async def closure():
            self.proxy = await DeviceProxy(self.trl)
            self.register_signals()

            return self

        return closure().__await__()

    # --------------------------------------------------------------------
    @abstractmethod
    def register_signals(self):
        """
        This method can be used to manually register signals
        """
