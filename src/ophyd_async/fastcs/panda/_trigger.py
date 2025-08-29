import asyncio

import numpy as np
from pydantic import Field
from scanspec.core import Path
from scanspec.specs import Spec

from ophyd_async.core import (
    ConfinedModel,
    FlyerController,
    error_if_none,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor

from ._block import (
    PandaBitMux,
    PandaPcompDirection,
    PandaTimeUnits,
    PcompBlock,
    SeqBlock,
)
from ._table import SeqTable, SeqTrigger


class SeqTableInfo(ConfinedModel):
    """Info for the PandA `SeqTable` for fly scanning."""

    sequence_table: SeqTable = Field(strict=True)
    repeats: int = Field(ge=0)
    prescale_as_us: float = Field(default=1, ge=0)  # microseconds


class ScanSpecInfo(ConfinedModel):
    spec: Spec[Motor]
    deadtime: float


class StaticSeqTableTriggerLogic(FlyerController[SeqTableInfo]):
    """For controlling the PandA `SeqTable` when fly scanning."""

    def __init__(self, seq: SeqBlock) -> None:
        self.seq = seq

    async def prepare(self, value: SeqTableInfo):
        await asyncio.gather(
            self.seq.prescale_units.set(PandaTimeUnits.US),
            self.seq.enable.set(PandaBitMux.ZERO),
        )
        await asyncio.gather(
            self.seq.prescale.set(value.prescale_as_us),
            self.seq.repeats.set(value.repeats),
            self.seq.table.set(value.sequence_table),
        )

    async def kickoff(self) -> None:
        await self.seq.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.seq.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        await self.seq.enable.set(PandaBitMux.ZERO)
        await wait_for_value(self.seq.active, False, timeout=1)


class ScanSpecSeqTableTriggerLogic(FlyerController[ScanSpecInfo]):
    def __init__(self, seq: SeqBlock, name="") -> None:
        self.seq = seq
        self.name = name

    async def prepare(self, value: ScanSpecInfo):
        await self.seq.enable.set(PandaBitMux.ZERO)
        slice = Path(value.spec.calculate()).consume()
        slice_duration = error_if_none(slice.duration, "Slice must have duration")

        # gaps = self._calculate_gaps(slice)
        gaps = np.where(slice.gap)[0]
        if gaps[0] == 0:
            gaps = np.delete(gaps, 0)
        scan_size = len(slice)

        gaps = np.append(gaps, scan_size)
        fast_axis = slice.axes()[-1]

        # Resolution from PandA Encoder
        resolution = await fast_axis.encoder_res.get_value()
        start = 0

        # GPIO goes low
        rows = SeqTable.row(trigger=SeqTrigger.BITA_0)
        for gap in gaps:
            # GPIO goes high
            rows += SeqTable.row(trigger=SeqTrigger.BITA_1)
            # Wait for position
            if (
                slice.midpoints[fast_axis][gap - 1] * resolution
                > slice.midpoints[fast_axis][start] * resolution
            ):
                trig = SeqTrigger.POSA_GT
                dir = False if resolution > 0 else True

            else:
                trig = SeqTrigger.POSA_LT
                dir = True if resolution > 0 else False
            rows += SeqTable.row(
                trigger=trig,
                position=int(slice.lower[fast_axis][start] / resolution),
            )

            # Time based Triggers
            rows += SeqTable.row(
                repeats=gap - start,
                trigger=SeqTrigger.IMMEDIATE,
                time1=int((slice_duration[0] - value.deadtime) * 10**6),
                time2=int(value.deadtime * 10**6),
                outa1=True,
                outb1=dir,
                outa2=False,
                outb2=dir,
            )

            # GPIO goes low
            rows += SeqTable.row(trigger=SeqTrigger.BITA_0)

            start = gap
        await asyncio.gather(
            self.seq.prescale.set(1.0),
            self.seq.prescale_units.set(PandaTimeUnits.US),
            self.seq.repeats.set(1),
            self.seq.table.set(rows),
        )

    async def kickoff(self) -> None:
        await self.seq.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.seq.active, True, timeout=1)

    async def complete(self) -> None:
        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        await self.seq.enable.set(PandaBitMux.ZERO)
        await wait_for_value(self.seq.active, False, timeout=1)


class PcompInfo(ConfinedModel):
    """Info for the PandA `PcompBlock` for fly scanning."""

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
    direction: PandaPcompDirection = Field(
        description=(
            "Specifies which direction the motor counts should be "
            "moving. Pulses won't be sent unless the values are moving in "
            "this direction."
        )
    )


class StaticPcompTriggerLogic(FlyerController[PcompInfo]):
    """For controlling the PandA `PcompBlock` when fly scanning."""

    def __init__(self, pcomp: PcompBlock) -> None:
        self.pcomp = pcomp

    async def prepare(self, value: PcompInfo):
        await self.pcomp.enable.set(PandaBitMux.ZERO)
        await asyncio.gather(
            self.pcomp.start.set(value.start_postion),
            self.pcomp.width.set(value.pulse_width),
            self.pcomp.step.set(value.rising_edge_step),
            self.pcomp.pulses.set(value.number_of_pulses),
            self.pcomp.dir.set(value.direction),
        )

    async def kickoff(self) -> None:
        await self.pcomp.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.pcomp.active, True, timeout=1)

    async def complete(self, timeout: float | None = None) -> None:
        await wait_for_value(self.pcomp.active, False, timeout=timeout)

    async def stop(self):
        await self.pcomp.enable.set(PandaBitMux.ZERO)
        await wait_for_value(self.pcomp.active, False, timeout=1)
