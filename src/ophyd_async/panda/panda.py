from __future__ import annotations

from enum import Enum

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceVector, SignalR, SignalRW
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.panda.table import SeqTable


class DataBlock(Device):
    hdf_directory: SignalRW[str, str]
    hdf_file_name: SignalRW[str, str]
    num_capture: SignalRW[int, int]
    num_captured: SignalR[int]
    capture: SignalRW[bool, bool]
    flush_period: SignalRW[float, float]


class PulseBlock(Device):
    delay: SignalRW[float, float]
    width: SignalRW[float, float]


class TimeUnits(str, Enum):
    min = "min"
    s = "s"
    ms = "ms"
    us = "us"


class SeqBlock(Device):
    table: SignalRW[SeqTable, SeqTable]
    active: SignalRW[bool, bool]
    repeats: SignalRW[int, int]
    prescale: SignalRW[float, float]
    prescale_units: SignalRW[TimeUnits, TimeUnits]
    enable: SignalRW[str, str]


class PcapBlock(Device):
    active: SignalR[bool]
    arm: SignalRW[bool, bool]


class CommonPandABlocks(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock


class PandA(CommonPandABlocks):
    data: DataBlock

    def __init__(self, prefix: str, name: str = "") -> None:
        self._prefix = prefix
        # Remove this assert once PandA IOC supports different prefixes
        assert prefix.endswith(":"), f"PandA prefix '{prefix}' must end in ':'"
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
