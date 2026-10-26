from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import cast

import numpy as np
from pydantic import Field
from scanspec.core import Path, Slice
from scanspec.specs import Spec

from ophyd_async.core import (
    AsyncStatus,
    ConfinedModel,
    FlyableLogic,
    SignalRW,
    error_if_none,
    observe_value,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor

from ._block import (
    CommonPandaBlocks,
    PandaBitMux,
    PandaPcompDirection,
    PandaPosMux,
    PandaSeqWrite,
    PandaTimeUnits,
    PcompBlock,
    SeqBlock,
)
from ._table import SeqTable, SeqTrigger

MAX_REPEATS = 2**16 - 1  # Maximum number of repeats for the PandA SeqTable row
MAX_TABLE_ROWS = 62500  # Panda SeqTable maximum number of rows


@dataclass
class PandaPrepareContext:
    path: Path
    deadtime: float
    scale: float
    offset: float
    has_pos_out: bool
    points_per_write: int
    # Get the lengths of the last two table written to set the refill treshold
    last_table_lengths: deque[int] = field(default_factory=lambda: deque(maxlen=2))


class SeqTableInfo(ConfinedModel):
    """Info for the PandA `SeqTable` for fly scanning."""

    sequence_table: SeqTable = Field(strict=True)
    repeats: int = Field(ge=0)
    prescale_as_us: float = Field(default=1, ge=0)  # microseconds


class ScanSpecInfo(ConfinedModel):
    spec: Spec[Motor]
    deadtime: float


@dataclass
class StaticSeqTableFlyableLogic(FlyableLogic[SeqTableInfo, None]):
    """For controlling the PandA `SeqTable` when fly scanning."""

    seq: SeqBlock

    async def on_prepare(self, value: SeqTableInfo):
        await asyncio.gather(
            self.seq.prescale_units.set(PandaTimeUnits.US),
            self.seq.enable.set(PandaBitMux.ZERO),
        )
        await asyncio.gather(
            self.seq.prescale.set(value.prescale_as_us),
            self.seq.repeats.set(value.repeats),
            self.seq.table.set(value.sequence_table),
        )

    async def on_kickoff(self, ctx: None) -> None:
        await self.seq.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.seq.active, True, timeout=1)

    async def on_complete(self, ctx: None) -> None:
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


@dataclass
class ScanSpecSeqTableFlyableLogic(FlyableLogic[ScanSpecInfo, PandaPrepareContext]):
    seq: SeqBlock
    motor_pos_outs: dict[Motor, PosOutScaleOffset] = field(default_factory=dict)
    _append_status: AsyncStatus | None = None

    def _split_repeats(self, repeats: int):
        filled_rows, remainder = divmod(repeats, MAX_REPEATS)
        repeats_list = [MAX_REPEATS] * filled_rows
        if remainder:
            repeats_list.append(remainder)
        return repeats_list

    def _points_per_write(self, path: Path, has_pos_out: bool) -> int:
        window_length = len(path.stack[-1])
        rows_per_window = (
            2  # BITA_0 and BITA_1
            + (1 if has_pos_out else 0)
            + ceil(window_length / MAX_REPEATS)
        )
        windows = max(1, MAX_TABLE_ROWS // rows_per_window)
        return windows * window_length

    async def _get_pos_out_scale_offset(self, slice: Slice):
        fast_axis = slice.axes()[-1]
        pos_out = self.motor_pos_outs.get(fast_axis)
        # If we have a motor to compare against, get its scale and offset
        # otherwise don't connect POSA to anything
        if pos_out is not None:
            has_pos_out = True
            scale, offset = await asyncio.gather(
                pos_out.scale.get_value(),
                pos_out.offset.get_value(),
            )
            compare_pos_name = cast(PandaPosMux, pos_out.name)
        else:
            scale, offset = 1, 0
            compare_pos_name = PandaPosMux.ZERO
            has_pos_out = False
        return has_pos_out, compare_pos_name, scale, offset

    def _build_rows(
        self,
        slice: Slice,
        deadtime: float,
        scale: float,
        offset: float,
        has_pos_out: bool,
    ) -> SeqTable:
        # Start of window is where the is a gap to the previous point
        slice_duration = error_if_none(slice.duration, "Slice must have duration")
        window_start = np.nonzero(slice.gap)[0]
        # End of window is either the next gap, or the end of the scan
        window_end = np.append(window_start[1:], len(slice))
        fast_axis = slice.axes()[-1]

        rows = SeqTable.empty()
        for start, end in zip(window_start, window_end, strict=True):
            # GPIO goes low then high
            rows += SeqTable.row(trigger=SeqTrigger.BITA_0)
            rows += SeqTable.row(trigger=SeqTrigger.BITA_1)
            # Wait for position if we are comparing against a motor

            if has_pos_out:
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
            repeats = end - start
            for repeat in self._split_repeats(repeats):
                rows += SeqTable.row(
                    repeats=repeat,
                    trigger=SeqTrigger.IMMEDIATE,
                    time1=int((slice_duration[0] - deadtime) * 10**6),
                    time2=int(deadtime * 10**6),
                    outa1=True,
                    outa2=False,
                )

        return rows

    async def _append_to_table(self, ctx: PandaPrepareContext) -> None:
        table_next_write = error_if_none(
            self.seq.table_next_write,
            "table_next_write signal is not available on this PandA",
        )
        remaining_points = len(ctx.path)
        if remaining_points < ctx.points_per_write:
            path_slice = ctx.path.consume(remaining_points)
        else:
            path_slice = ctx.path.consume(ctx.points_per_write)
        rows = self._build_rows(
            path_slice,
            ctx.deadtime,
            ctx.scale,
            ctx.offset,
            ctx.has_pos_out,
        )
        if len(ctx.last_table_lengths) == 0:
            next_write = PandaSeqWrite.APPEND
        elif len(ctx.path) == 0:
            await asyncio.sleep(5)
            next_write = PandaSeqWrite.APPEND_LAST
        else:
            await asyncio.sleep(5)
            next_write = PandaSeqWrite.APPEND
            await asyncio.sleep(5)
        await table_next_write.set(next_write)
        await self.seq.table.set(rows)
        ctx.last_table_lengths.append(len(rows))

    async def _append_and_monitor(self, ctx: PandaPrepareContext):

        table_line = error_if_none(
            self.seq.table_line,
            "table_line signal is not available on this PandA",
        )

        async for line in observe_value(table_line):
            processed_lines = 0
            processed_lines += ctx.last_table_lengths[-1]
            if line <= processed_lines:
                continue
            else:
                await self._append_to_table(ctx)

    async def on_prepare(self, value: ScanSpecInfo) -> PandaPrepareContext:
        await self.seq.enable.set(PandaBitMux.ZERO)
        path = Path(value.spec.calculate())
        (
            has_pos_out,
            compare_pos_name,
            scale,
            offset,
        ) = await self._get_pos_out_scale_offset(Path(path.stack, 0, 1).consume())

        ctx = PandaPrepareContext(
            path=path,
            deadtime=value.deadtime,
            scale=scale,
            offset=offset,
            has_pos_out=has_pos_out,
            points_per_write=self._points_per_write(path, has_pos_out),
        )

        # Need to do units before value for PandA, otherwise it scales the current value
        await self.seq.prescale_units.set(PandaTimeUnits.US)
        await asyncio.gather(
            self.seq.posa.set(compare_pos_name),
            self.seq.prescale.set(1.0),
            self.seq.repeats.set(1),
        )
        table_clear = error_if_none(
            self.seq.table_clear,
            "table_clear signal is not available on this PandA",
        )
        if table_clear is not None:
            await table_clear.trigger()
        await self._append_to_table(ctx)
        if len(ctx.path) > 0:
            await self._append_to_table(ctx)
        return ctx

    async def on_kickoff(self, ctx: PandaPrepareContext) -> PandaPrepareContext:
        await self.seq.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.seq.active, True, timeout=1)

        if len(ctx.path) > 0:
            self._append_status = AsyncStatus(self._append_and_monitor(ctx))
        return ctx

    async def on_complete(self, ctx: PandaPrepareContext) -> None:
        if self._append_status is not None:
            await self._append_status
            self._append_status = None

        await wait_for_value(self.seq.active, False, timeout=None)

    async def stop(self):
        if self._append_status is not None:
            self._append_status.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._append_status
            self._append_status = None

        await self.seq.enable.set(PandaBitMux.ZERO)
        await wait_for_value(self.seq.active, False, timeout=1)


class PcompInfo(ConfinedModel):
    """Info for the PandA `PcompBlock` for fly scanning."""

    start_position: int = Field(description="start position in counts")
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


@dataclass
class StaticPcompFlyableLogic(FlyableLogic[PcompInfo, None]):
    """For controlling the PandA `PcompBlock` when fly scanning."""

    pcomp: PcompBlock

    async def on_prepare(self, value: PcompInfo):
        await self.pcomp.enable.set(PandaBitMux.ZERO)
        await asyncio.gather(
            self.pcomp.start.set(value.start_position),
            self.pcomp.width.set(value.pulse_width),
            self.pcomp.step.set(value.rising_edge_step),
            self.pcomp.pulses.set(value.number_of_pulses),
            self.pcomp.dir.set(value.direction),
        )

    async def on_kickoff(self, ctx: None) -> None:
        await self.pcomp.enable.set(PandaBitMux.ONE)
        await wait_for_value(self.pcomp.active, True, timeout=1)

    async def on_complete(self, ctx: None) -> None:
        await wait_for_value(self.pcomp.active, False, timeout=None)

    async def stop(self):
        await self.pcomp.enable.set(PandaBitMux.ZERO)
        await wait_for_value(self.pcomp.active, False, timeout=1)
