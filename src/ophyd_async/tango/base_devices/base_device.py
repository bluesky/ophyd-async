"""Default Tango Devices"""

from __future__ import annotations

from abc import abstractmethod

from tango.asyncio import DeviceProxy

from ophyd_async.core import AsyncStatus, StandardReadable

__all__ = ("TangoReadableDevice",)


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
        This method should be used to register signals
        """

    # --------------------------------------------------------------------
    @AsyncStatus.wrap
    async def stage(self) -> None:
        for sig in self._read_signals + self._configuration_signals:
            if hasattr(sig, "is_cachable") and sig.is_cachable():
                await sig.stage().task

    # --------------------------------------------------------------------
    @AsyncStatus.wrap
    async def unstage(self) -> None:
        for sig in self._read_signals + self._configuration_signals:
            if hasattr(sig, "is_cachable") and sig.is_cachable():
                await sig.unstage().task
