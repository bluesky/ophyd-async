from typing import List

import bluesky.plan_stubs as bps

from ophyd_async.core.detector import DetectorTrigger, StandardDetector, TriggerInfo
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.utils import in_micros
from ophyd_async.panda._table import SeqTable, SeqTableRow, seq_table_from_rows
from ophyd_async.panda._trigger import SeqTableInfo


def prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
    flyer: HardwareTriggeredFlyable[SeqTableInfo],
    detectors: List[StandardDetector],
    number_of_frames: int,
    width: float,
    deadtime: float,
    shutter_time: float,
    repeats: int = 1,
    period: float = 0.0,
):
    trigger_info = TriggerInfo(
        number_of_frames=number_of_frames * repeats,
        trigger=DetectorTrigger.constant_gate,
        deadtime=deadtime,
        livetime=width,
    )

    trigger_time = number_of_frames * (width + deadtime)
    pre_delay = max(period - 2 * shutter_time - trigger_time, 0)

    table: SeqTable = seq_table_from_rows(
        # Wait for pre-delay then open shutter
        SeqTableRow(
            time1=in_micros(pre_delay),
            time2=in_micros(shutter_time),
            outa2=True,
        ),
        # Keeping shutter open, do N triggers
        SeqTableRow(
            repeats=number_of_frames,
            time1=in_micros(width),
            outa1=True,
            outb1=True,
            time2=in_micros(deadtime),
            outa2=True,
        ),
        # Add the shutter close
        SeqTableRow(time2=in_micros(shutter_time)),
    )

    table_info = SeqTableInfo(table, repeats)

    for det in detectors:
        yield from bps.prepare(det, trigger_info, wait=False, group="prep")
    yield from bps.prepare(flyer, table_info, wait=False, group="prep")
    yield from bps.wait(group="prep")
