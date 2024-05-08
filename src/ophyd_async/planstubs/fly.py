from typing import Optional

import bluesky.plan_stubs as bps

from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.planstubs import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
)


def fly(
    stream_name: str,
    detector_list: tuple[StandardDetector],
    flyer: HardwareTriggeredFlyable,
    number_of_frames: int,
    exposure: int,
    shutter_time: float,
    repeats: Optional[int],
    period: Optional[float],
):
    """Run a scan wth a flyer and multiple detectors.

    The standard basic flow for a flyscan.

    1. Set up and prepare a trigger

    2. fly and collect

    """
    deadtime = max(det.controller.get_deadtime(1) for det in detector_list)

    # sort repeats and period

    # Set up scan and prepare trigger
    yield from bps.stage_all(*detector_list, flyer)
    yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
        flyer,
        detector_list,
        number_of_frames,
        width=exposure,
        deadtime=deadtime,
        shutter_time=shutter_time,
        repeats=repeats,
        period=period,
    )
    yield from bps.open_run()
    yield from bps.declare_stream(*detector_list, name=stream_name, collect=True)

    # fly and collect
    yield from bps.kickoff_all(flyer, *detector_list)
    yield from bps.complete_all(flyer, *detector_list, group="complete")

    done = False
    while not done:
        yield from bps.wait(group="complete", timeout=0.5)
        yield from bps.collect(*detector_list, name=stream_name)

    yield from bps.wait(group="complete")

    # Finish
    yield from bps.close_run()
    yield from bps.unstage_all(flyer, *detector_list)
