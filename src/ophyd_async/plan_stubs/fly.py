from typing import Any, Callable, Concatenate, List, ParamSpec

import bluesky.plan_stubs as bps
from bluesky.utils import short_uid

from ophyd_async.core.detector import DetectorTrigger, StandardDetector, TriggerInfo
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.core.utils import in_micros
from ophyd_async.panda._table import SeqTable, SeqTableRow, seq_table_from_rows
from ophyd_async.panda._trigger import SeqTableInfo

P = ParamSpec("P")


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


def time_resolved_fly_and_collect_with_static_seq_table(
    stream_name: str,
    detectors: List[StandardDetector],
    flyer: HardwareTriggeredFlyable[SeqTableInfo],
    number_of_frames: int,
    exposure: float,
    shutter_time: float,
    repeats: int = 1,
    period: float = 0.0,
    prepare_flyer_and_detectors: Callable[
        Concatenate[HardwareTriggeredFlyable[SeqTableInfo], List[StandardDetector], P],
        Any,
    ] = prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
):
    """Run a scan wth a flyer and multiple detectors.

    The standard basic flow for a flyscan:

    - Set up the flyer with a static sequence table and detectors with a trigger
        (A plan stub callable is passed in to do this preperation)
    - Declare the stream and kickoff the scan
    - Collect while completing

    This needs to be used in a plan that instantates detectors and a flyer,
    stages/unstages the devices, and opens and closes the run.

    """
    if not detectors:
        raise ValueError("No detectors provided. There must be at least one.")

    # Set up scan and prepare trigger
    deadtime = max(det.controller.get_deadtime(exposure) for det in detectors)
    yield from prepare_flyer_and_detectors(
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
    yield from bps.kickoff(flyer, wait=True)
    for detector in detectors:
        yield from bps.kickoff(detector)

    # collect_while_completing
    group = short_uid(label="complete")

    yield from bps.complete(flyer, wait=False, group=group)
    for detector in detectors:
        yield from bps.complete(detector, wait=False, group=group)

    done = False
    while not done:
        try:
            yield from bps.wait(group=group, timeout=0.5)
        except TimeoutError:
            pass
        else:
            done = True
        yield from bps.collect(
            *detectors,
            return_payload=False,
            name=stream_name,
        )
    yield from bps.wait(group=group)
