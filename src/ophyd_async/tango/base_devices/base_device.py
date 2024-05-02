from __future__ import annotations

from abc import abstractmethod

from ophyd_async.core import DEFAULT_TIMEOUT, AsyncStatus, StandardReadable
from tango.asyncio import DeviceProxy

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

    # # --------------------------------------------------------------------
    # def __await__(self):
    #     async def closure():
    #         self.proxy = await DeviceProxy(self.trl)
    #         self.register_signals()
    #
    #         return self
    #
    #     return closure().__await__()

    # --------------------------------------------------------------------
    async def connect(self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT):
        async def closure():
            self.proxy = await DeviceProxy(self.trl)
            self.register_signals()
            return self

        await closure()
        await super().connect(sim=sim, timeout=timeout)

    # --------------------------------------------------------------------
    @abstractmethod
    def register_signals(self):
        """
        This method should be used to register signals
        """

    # --------------------------------------------------------------------
    @AsyncStatus.wrap
    async def stage(self) -> None:
        for sig in self._readables + self._configurables:
            if hasattr(sig, "is_cachable") and sig.is_cachable():
                await sig.stage().task

    # --------------------------------------------------------------------
    @AsyncStatus.wrap
    async def unstage(self) -> None:
        for sig in self._readables + self._configurables:
            if hasattr(sig, "is_cachable") and sig.is_cachable():
                await sig.unstage().task
