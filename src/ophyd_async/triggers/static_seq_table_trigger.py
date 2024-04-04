import asyncio
from dataclasses import dataclass

from ophyd_async.core import TriggerLogic, wait_for_value
from ophyd_async.panda import SeqBlock, SeqTable


@dataclass
class RepeatedSequenceTable:
    sequence_table: SeqTable
    repeats: int


class StaticSeqTableTriggerLogic(TriggerLogic[SeqTable]):

    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    async def prepare(self, value: RepeatedSequenceTable):
        await asyncio.gather(
            self.seq.prescale_units.set("us"),
            self.seq.enable.set("ZERO"),
        )
        await asyncio.gather(
            self.seq.prescale.set(1),
            self.seq.repeats.set(value.repeats),
            self.seq.table.set(value.sequence_table),
        )

    async def start(self):
        await self.seq.enable.set("ONE")
        await wait_for_value(self.seq.active, 1, timeout=1)
        await wait_for_value(self.seq.active, 0, timeout=None)

    async def stop(self):
        await self.seq.enable.set("ZERO")
        await wait_for_value(self.seq.active, 0, timeout=1)
