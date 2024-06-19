import asyncio
from typing import Sequence

from bluesky.protocols import Triggerable

from ophyd_async.core import (AsyncStatus, ConfigSignal, HintedSignal, SignalR,
                              StandardReadable)

from ._ad_base import ADBase
from ._utils import ImageMode
from ._writers._nd_plugin import NDPluginBase


class SingleTriggerDet(StandardReadable, Triggerable):
    def __init__(
        self,
        drv: ADBase,
        read_uncached: Sequence[SignalR] = (),
        name="",
        **plugins: NDPluginBase,
    ) -> None:
        self.drv = drv
        self.__dict__.update(plugins)

        self.add_readables(
            [self.drv.array_counter, *read_uncached],
            wrapper=HintedSignal.uncached,
        )

        self.add_readables([self.drv.acquire_time], wrapper=ConfigSignal)

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
