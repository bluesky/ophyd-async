import asyncio

from ophyd_async.core import TriggerLogic, wait_for_value
from ophyd_async.panda import SeqTable, SeqBlock


class StaticSeqTableTriggerLogic(TriggerLogic[SeqTable]):

    def __init__(self, seq: SeqBlock, shutter_time: float = 0) -> None:
        self.seq = seq
        self.shutter_time = shutter_time
        self.repeats = 1

    async def prepare(self, value: SeqTable):
        await asyncio.gather(
            self.seq.prescale_units.set("us"),
            self.seq.enable.set("ZERO"),
        )
        await asyncio.gather(
            self.seq.prescale.set(1),
            self.seq.repeats.set(self.repeats),
            self.seq.table.set(value),
        )

    async def start(self):
        await self.seq.enable.set("ONE")
        await wait_for_value(self.seq.active, 1, timeout=1)
        await wait_for_value(self.seq.active, 0, timeout=None)

    async def stop(self):
        await self.seq.enable.set("ZERO")
        await wait_for_value(self.seq.active, 0, timeout=1)