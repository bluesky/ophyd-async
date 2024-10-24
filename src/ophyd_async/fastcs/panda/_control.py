import asyncio

from ophyd_async.core import (
    DetectorController,
    DetectorTrigger,
    wait_for_value,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.core._status import AsyncStatus

from ._block import PcapBlock


class PandaPcapController(DetectorController):
    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.000000008

    async def prepare(self, trigger_info: TriggerInfo):
        assert trigger_info.trigger in (
            DetectorTrigger.constant_gate,
            DetectorTrigger.variable_gate,
        ), "Only constant_gate and variable_gate triggering is supported on the PandA"

    async def arm(self):
        self._arm_status = self.pcap.arm.set(True)
        await wait_for_value(self.pcap.active, True, timeout=1)

    async def wait_for_idle(self):
        pass

    async def disarm(self):
        await asyncio.gather(self.pcap.arm.set(False))
        await wait_for_value(self.pcap.active, False, timeout=1)
