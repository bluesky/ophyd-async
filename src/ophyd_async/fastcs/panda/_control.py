import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    wait_for_value,
)
from ophyd_async.core._detector import TriggerInfo

from ._block import PcapBlock


class PandaPcapController(DetectorControl):
    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    def get_deadtime(self, exposure: float) -> float:
        return 0.000000008

    async def prepare(self, trigger_info: TriggerInfo):
        assert trigger_info.trigger in (
            DetectorTrigger.constant_gate,
            DetectorTrigger.variable_gate,
        ), "Only constant_gate and variable_gate triggering is supported on the PandA"
        await asyncio.gather(self.pcap.arm.set(True))
        await wait_for_value(self.pcap.active, True, timeout=1)

    def arm(self):
        self._arm_status = AsyncStatus(
            wait_for_value(self.pcap.active, False, timeout=None)
        )

    async def wait_for_armed(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        await asyncio.gather(self.pcap.arm.set(False))
        await wait_for_value(self.pcap.active, False, timeout=1)
