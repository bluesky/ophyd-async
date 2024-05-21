from typing import List

import bluesky.plan_stubs as bps

from ophyd_async.core.detector import (DetectorTrigger, StandardDetector,
                                       TriggerInfo)
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.utils import in_micros
from ophyd_async.panda._table import SeqTable, SeqTableRow, seq_table_from_rows
from ophyd_async.panda._trigger import SeqTableInfo


def time_resolved_fly_and_collect_with_static_seq_table(
    stream_name: str,
    detectors: List[StandardDetector],
    flyer: HardwareTriggeredFlyable[SeqTableInfo],
    number_of_frames: int,
    exposure: int,
    shutter_time: float,
    repeats: int = 1,
    period: float = 0.0,
):
    """Run a scan wth a flyer and multiple detectors.

    The standard basic flow for a flyscan:

    - Set up the flyer with a static sequence table and detectors with a trigger
    - Declare the stream and kickoff the scan
    - Collect while completing

    This needs to be used in a plan that instantates detectors and a flyer,
    stages/unstages the devices, and opens and closes the run.

    """
    # Set up scan and prepare trigger
    deadtime = max(det.controller.get_deadtime(exposure) for det in detectors)
    yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
        flyer,
        detectors,
        number_of_frames=number_of_frames,
        exposure=exposure,
        deadtime=deadtime,
        shutter_time=shutter_time,
        repeats=repeats,
        period=period,
    )
    yield from bps.declare_stream(*detectors, name=stream_name, collect=True)
    yield from bps.kickoff_all(flyer, *detectors)

    # collect_while_completing
    yield from bps.collect_while_completing(
        [flyer], detectors, flush_period=0.5, stream_name=stream_name
    )


def prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
    flyer: HardwareTriggeredFlyable[SeqTableInfo],
    detectors: List[StandardDetector],
    number_of_frames: int,
    exposure: float,
    deadtime: float,
    shutter_time: float,
    repeats: int = 1,
    period: float = 0.0,
):
    """Prepare a hardware triggered flyable and one or more detectors.

    Prepare a hardware triggered flyable and one or more detectors with the
    same trigger. This method constructs TriggerInfo and a static sequence
    table from required parameters. The table is required to prepare the flyer,
    and the TriggerInfo is required to prepare the detector(s).

    This prepares all supplied detectors with the same trigger.

    """
    trigger_info = TriggerInfo(
        num=number_of_frames * repeats,
        trigger=DetectorTrigger.constant_gate,
        deadtime=deadtime,
        livetime=exposure,
    )

    trigger_time = number_of_frames * (exposure + deadtime)
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
            time1=in_micros(exposure),
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
