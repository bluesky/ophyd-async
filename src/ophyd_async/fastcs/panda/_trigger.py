import asyncio
from typing import Optional

from pydantic import BaseModel, Field
from scanspec.specs import Spec

from ophyd_async.core import TriggerLogic, wait_for_value

from ._block import PcompBlock, PcompDirectionOptions, SeqBlock, TimeUnits
from ._table import SeqTable


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


class StaticPcompTriggerLogic(TriggerLogic[PcompInfo]):
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

    async def complete(self, timeout: Optional[float] = None) -> None:
        await wait_for_value(self.pcomp.active, False, timeout=timeout)

    async def stop(self):
        await self.pcomp.enable.set("ZERO")
        await wait_for_value(self.pcomp.active, False, timeout=1)


class PosTrigSeqInfo(BaseModel):
    spec: Spec[str]
    prescale_as_us: float = Field(default=1, ge=0)


class PosTrigSeqLogic(TriggerLogic[PosTrigSeqInfo]):
    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    def populate_seq_table(self, value: PosTrigSeqInfo) -> SeqTable:
        """
        Using scanspec this method will populate the
        SEQ table with chunks of frames.

        Multiple frames can be triggered with one line on SEQ table.
        When we have a gap in the numpy frames (depicted by gap=True).
        This depicts a PCOMP point and requires a new line on the SEQ table

        SEQ tables have a row limit of 1024. We need to dynamically populate the SEQ
        table for an arbitary number of frames and gaps (for arbitary trajectories).
        We want to take a chunk of frames recieved from scanspec, populate a SEQ table
        in prepare, then complete.

        While completing we will be checking for the condition that the end of the
        table has been reached. Then we need to populate the table again with the
        next chunk of the scanspec frames.This need to repeat until it has completed.
        """

        # frames = value.spec.calculate()

    async def prepare(self, value: PosTrigSeqInfo):
        await asyncio.gather(
            self.seq.prescale_units.set(TimeUnits.us),
            self.seq.enable.set("ZERO"),
        )

        # table: SeqTable = seq_table_from_rows(
        #     SeqTableRow(
        #         time1=in_micros(pre_delay),
        #         time2=in_micros(shutter_time),
        #         outa2=True,
        #     ),
        #     # Keeping shutter open, do N triggers
        #     SeqTableRow(
        #         repeats=number_of_frames,
        #         time1=in_micros(exposure),
        #         outa1=True,
        #         outb1=True,
        #         time2=in_micros(deadtime),
        #         outa2=True,
        #     ),
        #     # Add the shutter close
        #     SeqTableRow(time2=in_micros(shutter_time)),
        # # )
        # await asyncio.gather(
        #     self.seq.prescale.set(value.prescale_as_us),
        #     self.seq.repeats.set(1),
        #     self.seq.table.set(table),
        # )

    async def kickoff(self) -> None:
        await self.seq.enable.set("ONE")
        await wait_for_value(self.seq.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        await self.seq.enable.set("ZERO")
        await wait_for_value(self.seq.active, False, timeout=1)
