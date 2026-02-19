from ophyd_async.core import (
    DetectorArmLogic,
    set_and_wait_for_other_value,
)

from ._block import PcapBlock


class PandaArmLogic(DetectorArmLogic):
    """For controlling arm/disarm of PandA data blocks."""

    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    async def arm(self):
        await set_and_wait_for_other_value(self.pcap.arm, True, self.pcap.active, True)

    async def wait_for_idle(self):
        # TODO: https://github.com/PandABlocks/PandABlocks-FPGA/issues/262
        pass

    async def disarm(self):
        await set_and_wait_for_other_value(
            self.pcap.arm, False, self.pcap.active, False
        )
