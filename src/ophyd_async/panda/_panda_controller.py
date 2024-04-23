import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    wait_for_value,
)
from ophyd_async.panda import PcapBlock


class PandaPcapController(DetectorControl):
    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    def get_deadtime(self, exposure: float) -> float:
        return 0.000000008

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.constant_gate,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        assert trigger in (
            DetectorTrigger.constant_gate,
            trigger == DetectorTrigger.variable_gate,
        ), "Only constant_gate and variable_gate triggering is supported on the PandA"
        await asyncio.gather(self.pcap.arm.set(True))
        await wait_for_value(self.pcap.active, True, timeout=1)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))

    async def disarm(self) -> AsyncStatus:
        await asyncio.gather(self.pcap.arm.set(False))
        await wait_for_value(self.pcap.active, False, timeout=1)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))
