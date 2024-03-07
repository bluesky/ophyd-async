import asyncio
from typing import Optional

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger

from .panda import PcapBlock


class PandaPcapController(DetectorControl):
    def __init__(
        self,
        pandaPcap: PcapBlock,
    ) -> None:
        self.pandaPcap = pandaPcap

    def get_deadtime(self, exposure: float) -> float:
        return 0.000000008

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        assert (
            trigger == DetectorTrigger.internal
        ), "Only internal triggering is supported on the PandA"
        self.pandaPcap.arm.trigger()
        return AsyncStatus(asyncio.sleep(0.1))

    async def disarm(self):
        self.pandaPcap.disarm.trigger(),
