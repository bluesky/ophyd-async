from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

import numpy as np
from pydantic import Field
from scanspec.core import Path
from scanspec.specs import Spec

from ophyd_async.core import (
    ConfinedModel,
    FlyerController,
    SignalRW,
    error_if_none,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor

from ._block import (
    CommonPandaBlocks,
    PandaBitMux,
    PandaPcompDirection,
    PandaPosMux,
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


@dataclass
class PosOutScaleOffset:
    name: str
    scale: SignalRW[float]
    offset: SignalRW[float]

    @classmethod
    def from_inenc(cls, panda: CommonPandaBlocks, number: int) -> PosOutScaleOffset:
        inenc = panda.inenc[number]  # type: ignore
        return cls(
            name=f"INENC{number}.VAL",
            scale=inenc.val_scale,  # type: ignore
            offset=inenc.val_offset,  # type: ignore
        )


class ScanSpecSeqTableTriggerLogic(FlyerController[ScanSpecInfo]):
    def __init__(
        self,
        seq: SeqBlock,
        motor_pos_outs: dict[Motor, PosOutScaleOffset] | None = None,
    ) -> None:
        self.seq = seq
        self.motor_pos_outs = motor_pos_outs or {}

    async def prepare(self, value: ScanSpecInfo):
        await self.seq.enable.set(PandaBitMux.ZERO)
        slice = Path(value.spec.calculate()).consume()
        slice_duration = error_if_none(slice.duration, "Slice must have duration")

        # Start of window is where the is a gap to the previous point
        window_start = np.nonzero(slice.gap)[0]
        # End of window is either the next gap, or the end of the scan
        window_end = np.append(window_start[1:], len(slice))
        fast_axis = slice.axes()[-1]
        pos_out = self.motor_pos_outs.get(fast_axis)
        # If we have a motor to compare against, get its scale and offset
        # otherwise don't connect POSA to anything
        if pos_out is not None:
            scale, offset = await asyncio.gather(
                pos_out.scale.get_value(),
                pos_out.offset.get_value(),
            )
            compare_pos_name = cast(PandaPosMux, pos_out.name)
        else:
            scale, offset = 1, 0
            compare_pos_name = PandaPosMux.ZERO

        rows = SeqTable.empty()
        for start, end in zip(window_start, window_end, strict=True):
            # GPIO goes low then high
            rows += SeqTable.row(trigger=SeqTrigger.BITA_0)
            rows += SeqTable.row(trigger=SeqTrigger.BITA_1)
            # Wait for position if we are comparing against a motor
            if pos_out is not None:
                lower = (slice.lower[fast_axis][start] - offset) / scale
                midpoint = (slice.midpoints[fast_axis][start] - offset) / scale
                if midpoint > lower:
                    trigger = SeqTrigger.POSA_GT
                elif midpoint < lower:
                    trigger = SeqTrigger.POSA_LT
                else:
                    trigger = None
                if trigger is not None:
                    rows += SeqTable.row(
                        trigger=trigger,
                        position=int(lower),
                    )

            # Time based Triggers
            rows += SeqTable.row(
                repeats=end - start,
                trigger=SeqTrigger.IMMEDIATE,
                time1=int((slice_duration[0] - value.deadtime) * 10**6),
                time2=int(value.deadtime * 10**6),
                outa1=True,
                outa2=False,
            )
        # Need to do units before value for PandA, otherwise it scales the current value
        await self.seq.prescale_units.set(PandaTimeUnits.US)
        await asyncio.gather(
            self.seq.posa.set(compare_pos_name),
            self.seq.prescale.set(1.0),
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
