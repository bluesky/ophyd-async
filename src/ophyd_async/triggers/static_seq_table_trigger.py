import asyncio
from dataclasses import dataclass

from ophyd_async.core import TriggerLogic, wait_for_value
from ophyd_async.panda import SeqBlock, SeqTable
from ophyd_async.panda.panda import TimeUnits


@dataclass
class SequenceTableInfo:
    sequence_table: SeqTable
    repeats: int
    prescale_as_us: float = 1  # microseconds


class StaticSeqTableTriggerLogic(TriggerLogic[SequenceTableInfo]):

    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    async def prepare(self, value: SequenceTableInfo):
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
