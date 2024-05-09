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
    repeats: int = 1,
    period: float = 0.0,
):
    """Run a scan wth a flyer and multiple detectors.

    The standard basic flow for a flyscan:

    - Set up the flyer with a static sequence table and detectors with a trigger
    - Declare the stream and kickoff the scan
    - Collect while completing

    This needs to be used in a plan that instantates detectors and a flyer,
    stages/unstages the devices and opens and closes the run.

    """
    # Set up scan and prepare trigger
    deadtime = max(det.controller.get_deadtime(1) for det in detector_list)
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
    yield from bps.declare_stream(*detector_list, name=stream_name, collect=True)
    yield from bps.kickoff_all(flyer, *detector_list)

    # collect_while_completing
    yield from bps.complete_all(flyer, *detector_list, group="complete")

    done = False
    while not done:
        done = yield from bps.wait(group="complete", timeout=0.5)
        yield from bps.collect(*detector_list, name=stream_name)
