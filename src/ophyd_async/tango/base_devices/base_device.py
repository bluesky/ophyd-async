from __future__ import annotations

from typing import Optional

from ophyd_async.core import DEFAULT_TIMEOUT, StandardReadable
from tango.asyncio import DeviceProxy

__all__ = ("TangoReadableDevice",)


# --------------------------------------------------------------------
class TangoReadableDevice(StandardReadable):
    """
    General class for TangoDevices. Extends StandardReadable to provide
    attributes for Tango devices.

    Usage: to proper signals mount should be awaited:
    new_device = await TangoDevice(<tango_device>)

    attributes:
        trl:        Tango resource locator, typically of the device server.
        proxy:      DeviceProxy object for the device. This is created when the device
                    is connected.
        src_dict:   Dictionary of the device's attributes. This can be used to account
                    for variation in attribute names across similar servers.
    """

    src_dict: dict = {}
    trl: str = ""
    proxy: Optional[DeviceProxy] = None

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        self.trl = trl
        self.proxy: Optional[DeviceProxy] = None
        StandardReadable.__init__(self, name=name)

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        async def closure():
            self.proxy = await DeviceProxy(self.trl)
            return self

        await closure()
        await super().connect(mock=mock, timeout=timeout)

    # --------------------------------------------------------------------
    # @AsyncStatus.wrap
    # async def stage(self) -> None:
    #     for sig in self._readables + self._configurables:
    #         if hasattr(sig, "is_cachable") and sig.is_cachable():
    #             await sig.stage().task
    #
    # # --------------------------------------------------------------------
    # @AsyncStatus.wrap
    # async def unstage(self) -> None:
    #     for sig in self._readables + self._configurables:
    #         if hasattr(sig, "is_cachable") and sig.is_cachable():
    #             await sig.unstage().task
