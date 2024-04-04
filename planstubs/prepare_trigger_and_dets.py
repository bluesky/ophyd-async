import bluesky.plan_stubs as bps

from ophyd_async.core.detector import DetectorTrigger, StandardDetector, TriggerInfo
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.utils import in_micros
from ophyd_async.panda.table import SeqTable, SeqTableRow, seq_table_from_rows
from ophyd_async.triggers.static_seq_table_trigger import RepeatedSequenceTable


def prepare_static_seq_table_flyer_and_detector(
    flyer: HardwareTriggeredFlyable[SeqTable],
    detector: StandardDetector,
    num: int,
    width: float,
    deadtime: float,
    shutter_time: float,
    repeats: int = 1,
    period: float = 0.0,
):

    trigger_info = TriggerInfo(
        num=num * repeats,
        trigger=DetectorTrigger.constant_gate,
        deadtime=deadtime,
        livetime=width,
    )

    trigger_time = num * (width + deadtime)
    pre_delay = max(period - 2 * shutter_time - trigger_time, 0)

    table = seq_table_from_rows(
        # Wait for pre-delay then open shutter
        SeqTableRow(
            time1=in_micros(pre_delay),
            time2=in_micros(shutter_time),
            outa2=True,
        ),
        # Keeping shutter open, do N triggers
        SeqTableRow(
            repeats=num,
            time1=in_micros(width),
            outa1=True,
            outb1=True,
            time2=in_micros(deadtime),
            outa2=True,
        ),
        # Add the shutter close
        SeqTableRow(time2=in_micros(shutter_time)),
    )

    repeated_table = RepeatedSequenceTable(table, repeats)

    yield from bps.prepare(detector, trigger_info, wait=False, group="thing")
    yield from bps.prepare(flyer, repeated_table, wait=False, group="thing")
    yield from bps.wait(group="thing")
