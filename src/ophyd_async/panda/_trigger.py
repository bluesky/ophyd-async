import asyncio
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from ophyd_async.core import TriggerLogic, wait_for_value
from ophyd_async.panda import (
    PcompBlock,
    PcompDirectionOptions,
    SeqBlock,
    SeqTable,
    TimeUnits,
)


class SeqTableInfo(BaseModel):
    sequence_table: SeqTable = Field(strict=True)
    repeats: int = Field(ge=0)
    prescale_as_us: float = Field(default=1, ge=0)  # microseconds


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


class PcompInfo(BaseModel):
    start_postion: int = Field()  # start position in counts
    pulse_width: int = Field(gt=0)  # width of a single pulse in counts
    rising_edge_step: int = Field(gt=0)  # step between rising edges of pulses in counts
    number_of_pulses: int = Field(ge=0)
    direction: PcompDirectionOptions = Field()  # direction positive or negative

    @field_validator("direction", mode="before")
    def convert_enum_to_string(cls, value):
        if issubclass(type(value), Enum):
            return value.value
        return value


class StaticPcompTriggerLogic(TriggerLogic[PcompInfo]):
    def __init__(self, pcomp: PcompBlock) -> None:
        self.pcomp = pcomp

    async def prepare(self, value: PcompInfo):
        await self.pcomp.enable.set("ZERO")
        asyncio.gather(
            self.pcomp.start.set(value.start_postion),
            self.pcomp.width.set(value.pulse_width),
            self.pcomp.step.set(value.rising_edge_step),
            self.pcomp.pulses.set(value.number_of_pulses),
            self.pcomp.dir.set(value.direction),
        )

    async def kickoff(self) -> None:
        await self.pcomp.enable.set("ONE")
        await wait_for_value(self.pcomp.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.pcomp.active, False, timeout=None)

    async def stop(self):
        await self.pcomp.enable.set("ZERO")
        await wait_for_value(self.pcomp.active, False, timeout=1)
