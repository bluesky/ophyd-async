import asyncio
from dataclasses import dataclass
from typing import Literal

from ophyd_async.core import TriggerLogic, wait_for_value
from ophyd_async.panda import SeqBlock, SeqTable, TimeUnits


@dataclass
class SeqTableInfo:
    sequence_table: SeqTable
    repeats: int
    prescale_as_us: float = 1  # microseconds


class StaticSeqTableTriggerLogic(TriggerLogic[SeqTableInfo]):
    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    async def prepare(self, value: SeqTableInfo):
        await asyncio.gather(
            self.seq.prescale_units.set(TimeUnits.us),
            self.seq.enable.set("ZERO"),
        )
        await asyncio.gather(
            self.seq.prescale.set(value.prescale_as_us),
            self.seq.repeats.set(value.repeats),
            self.seq.table.set(value.sequence_table),
        )

    async def kickoff(self) -> None:
        await self.seq.enable.set("ONE")
        await wait_for_value(self.seq.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        await self.seq.enable.set("ZERO")
        await wait_for_value(self.seq.active, False, timeout=1)


@dataclass
class PcompTableInfo:
    start_postion: int  # start position in counts
    pulse_width: int  # width of a single pulse in counts
    rising_edge_step: int  # step between rising edges of pulses in counts
    number_of_pulses: int
    direction: Literal[-1, 1]  # direction positive or negative


class StaticPcompTableTriggerLogic(TriggerLogic[PcompTableInfo]):
    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    async def prepare(self, value: PcompTableInfo):
        await asyncio.gather(
            self.seq.prescale_units.set(TimeUnits.us),
            self.seq.enable.set("ZERO"),
        )
        await asyncio.gather(
            self.seq.prescale.set(value.prescale_as_us),
            self.seq.repeats.set(value.repeats),
            self.seq.table.set(value.sequence_table),
        )

    async def kickoff(self) -> None:
        await self.seq.enable.set("ONE")
        await wait_for_value(self.seq.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        await self.seq.enable.set("ZERO")
        await wait_for_value(self.seq.active, False, timeout=1)
