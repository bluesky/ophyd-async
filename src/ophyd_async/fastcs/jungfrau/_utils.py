from pydantic import PositiveInt

from ophyd_async.core import DetectorTrigger, TriggerInfo


def create_jungfrau_external_triggering_info(
    total_triggers: PositiveInt,
    exposure_time_s: float,
) -> TriggerInfo:
    """Create safe Jungfrau TriggerInfo for external triggering.

    Uses parameters which more closely-align with Jungfrau terminology
    to create TriggerInfo. This device currently only supports one frame per trigger
    when being externally triggered, but support for this can be added if needed

    Args:
        total_triggers: Total external triggers expected before ending acquisition.
        exposure_time_s: How long to expose the detector for each of its frames.

    Returns:
        `TriggerInfo`
    """
    return TriggerInfo(
        number_of_events=total_triggers,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        livetime=exposure_time_s,
    )


def create_jungfrau_internal_triggering_info(
    number_of_frames: PositiveInt, exposure_time_s: float
) -> TriggerInfo:
    """Create safe Jungfrau TriggerInfo for internal triggering.

    Uses parameters which more closely-align with Jungfrau terminology
    to create TriggerInfo.

    Args:
        number_of_frames: Total frames taken after starting acquisition.
        exposure_time_s: How long to expose the detector for each of its frames.

    Returns:
        `TriggerInfo`
    """
    return TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.INTERNAL,
        livetime=exposure_time_s,
        exposures_per_event=number_of_frames,
    )


def create_jungfrau_pedestal_triggering_info(
    exposure_time_s: float,
    pedestal_frames: PositiveInt,
    pedestal_loops: PositiveInt,
):
    """Create safe Jungfrau TriggerInfo for pedestal triggering.

    Uses parameters which more closely-align with Jungfrau terminology
    to create TriggerInfo.

    NOTE: To trigger the jungfrau in pedestal mode, you must first set the
    jungfrau acquisition_type signal to AcquisitionType.PEDESTAL!

    Args:
        exposure_time_s: How long to expose the detector for each of its frames.
        pedestal_frames: Number of frames taken once triggering begins
        pedestal_loops: Number of repeats of the pedestal scan before detector disarms.

    Returns:
        `TriggerInfo`
    """
    return TriggerInfo(
        number_of_events=pedestal_loops,
        exposures_per_event=pedestal_frames,
        trigger=DetectorTrigger.INTERNAL,
        livetime=exposure_time_s,
    )
