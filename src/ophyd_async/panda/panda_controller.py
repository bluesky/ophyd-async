import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    wait_for_value,
)
from ophyd_async.epics.pvi import PVIDependent

from .panda import PandA, PcapBlock


def _check_for_blocks(device, *blocks):
    for block in blocks:
        if not hasattr(device, block):
            raise RuntimeError(
                f"{block} block not found in {type(device)}, "
                "are you sure the panda has been connected?"
            )


class PandaPcapController(DetectorControl, PVIDependent):
    pcap: PcapBlock  # pcap will be given by the panda post connect

    def __init__(self) -> None:
        pass

    def get_deadtime(self, exposure: float) -> float:
        return 0.000000008

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.constant_gate,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        _check_for_blocks(self, "pcap")
        assert trigger in (
            DetectorTrigger.constant_gate,
            trigger == DetectorTrigger.variable_gate,
        ), "Only constant_gate and variable_gate triggering is supported on the PandA"
        await asyncio.gather(self.pcap.arm.set(True))
        await wait_for_value(self.pcap.active, True, timeout=1)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))

    async def disarm(self) -> AsyncStatus:
        _check_for_blocks(self, "pcap")
        await asyncio.gather(self.pcap.arm.set(False))
        await wait_for_value(self.pcap.active, False, timeout=1)
        return AsyncStatus(wait_for_value(self.pcap.active, False, timeout=None))

    def fill_blocks(self, connected_panda: PandA) -> None:
        _check_for_blocks(connected_panda, "pcap")
        self.pcap = connected_panda.pcap
