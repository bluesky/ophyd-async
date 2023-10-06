import asyncio
from typing import Sequence

from bluesky.protocols import Triggerable

from ophyd_async.core import AsyncStatus, SignalR, StandardReadable

from .drivers.ad_driver import ADDriver
from .utils import ImageMode
from .writers.nd_plugin import NDPlugin


class SingleTriggerDet(StandardReadable, Triggerable):
    def __init__(
        self,
        drv: ADDriver,
        read_uncached: Sequence[SignalR] = (),
        name="",
        **plugins: NDPlugin,
    ) -> None:
        self.drv = drv
        self.__dict__.update(plugins)
        self.set_readable_signals(
            # Can't subscribe to read signals as race between monitor coming back and
            # caput callback on acquire
            read_uncached=[self.drv.array_counter] + list(read_uncached),
            config=[self.drv.acquire_time],
        )
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
        )
        await super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        await self.drv.acquire.set(True)
