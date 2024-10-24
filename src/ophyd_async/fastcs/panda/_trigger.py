import asyncio

from pydantic import BaseModel, Field

from ophyd_async.core import FlyerController, wait_for_value

from ._block import PcompBlock, PcompDirectionOptions, SeqBlock, TimeUnits
from ._table import SeqTable


class SeqTableInfo(BaseModel):
    sequence_table: SeqTable = Field(strict=True)
    repeats: int = Field(ge=0)
    prescale_as_us: float = Field(default=1, ge=0)  # microseconds


class StaticSeqTableTriggerLogic(FlyerController[SeqTableInfo]):
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
    start_postion: int = Field(description="start position in counts")
    pulse_width: int = Field(description="width of a single pulse in counts", gt=0)
    rising_edge_step: int = Field(
        description="step between rising edges of pulses in counts", gt=0
    )  #
    number_of_pulses: int = Field(
        description=(
            "Number of pulses to send before the PCOMP block is disarmed. "
            "0 means infinite."
        ),
        ge=0,
    )
    direction: PcompDirectionOptions = Field(
        description=(
            "Specifies which direction the motor counts should be "
            "moving. Pulses won't be sent unless the values are moving in "
            "this direction."
        )
    )


class StaticPcompTriggerLogic(FlyerController[PcompInfo]):
    def __init__(self, pcomp: PcompBlock) -> None:
        self.pcomp = pcomp

    async def prepare(self, value: PcompInfo):
        await self.pcomp.enable.set("ZERO")
        await asyncio.gather(
            self.pcomp.start.set(value.start_postion),
            self.pcomp.width.set(value.pulse_width),
            self.pcomp.step.set(value.rising_edge_step),
            self.pcomp.pulses.set(value.number_of_pulses),
            self.pcomp.dir.set(value.direction),
        )

    async def kickoff(self) -> None:
        await self.pcomp.enable.set("ONE")
        await wait_for_value(self.pcomp.active, True, timeout=1)

    async def complete(self, timeout: float | None = None) -> None:
        await wait_for_value(self.pcomp.active, False, timeout=timeout)

    async def stop(self):
        await self.pcomp.enable.set("ZERO")
        await wait_for_value(self.pcomp.active, False, timeout=1)
