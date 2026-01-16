from ophyd_async.core import (
    DetectorArmLogic,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
    wait_for_value,
)

from ._block import PcapBlock


class PandaArmLogic(DetectorArmLogic):
    """For controlling arm/disarm of PandA data blocks."""

    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    async def arm(self):
        await set_and_wait_for_other_value(self.pcap.arm, True, self.pcap.active, True)

    async def wait_for_idle(self):
        await wait_for_value(self.pcap.active, False, timeout=None)

    async def disarm(self):
        await set_and_wait_for_value(self.pcap.arm, False)
