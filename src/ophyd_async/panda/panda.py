from __future__ import annotations

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceVector, SignalR, SignalRW
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.panda.table import SeqTable


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


class SeqBlock(Device):
    table: SignalRW[SeqTable]
    active: SignalRW[bool]


class PcapBlock(Device):
    active: SignalR[bool]
    arm: SignalRW[bool]


class CommonPandABlocks(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock


class PandA(CommonPandABlocks):
    def __init__(self, prefix: str, name: str = "") -> None:
        self._prefix = prefix
        super().__init__(name)

    async def connect(
        self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        """Initialises all blocks and connects them.

        First, checks for pvi information. If it exists, make all blocks from this.
        Then, checks that all required blocks in the PandA have been made.

        If there's no pvi information, that's because we're in sim mode. In that case,
        makes all required blocks.
        """

        await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)

        await super().connect(sim)
