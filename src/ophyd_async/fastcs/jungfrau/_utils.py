from pydantic import PositiveInt

from ophyd_async.core import DetectorTrigger, TriggerInfo

from ._controller import JUNGFRAU_DEADTIME_S


def create_jungfrau_external_triggering_info(
    total_triggers: PositiveInt,
    frames_per_trigger: PositiveInt,
    exposure_time_s: float,
    period_between_frames_s: float | None = None,
) -> TriggerInfo:
    """Create safe Jungfrau TriggerInfo for external triggering.

    Uses parameters which more closely-align with Jungfrau terminology
    to create TriggerInfo.

    Args:
        total_triggers: Total external triggers expected before ending acquisition.
        frames_per_trigger: How many frames to take for each external trigger.
        exposure_time_s: How long to expose the detector for each of its frames.
        period_between_frames_s: Time between each frame, including deadtime. Not
        required if frames_per_trigger is 1

    Returns:
        `TriggerInfo`
    """
    if frames_per_trigger > 1 and period_between_frames_s is None:
        raise ValueError("Must specify period_between_frames if frames_per_trigger > 1")
    elif period_between_frames_s:
        deadtime = _validate_then_get_deadtime(exposure_time_s, period_between_frames_s)
    else:
        deadtime = 0  # Gets set to JF controller deadtime during prepare

    return TriggerInfo(
        number_of_events=total_triggers,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        exposures_per_event=frames_per_trigger,
        livetime=exposure_time_s,
        deadtime=deadtime,
    )


def create_jungfrau_internal_triggering_info(
    number_of_frames: PositiveInt, exposure_time_s: float
) -> TriggerInfo:
    """Create safe Jungfrau TriggerInfo for internal triggering.

    Uses parameters which more closely-align with Jungfrau terminology
    to create TriggerInfo. Frames

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


def _validate_then_get_deadtime(
    exposure_time: float, period_between_frames: float
) -> float:
    deadtime = period_between_frames - exposure_time
    if deadtime < JUNGFRAU_DEADTIME_S:
        raise ValueError(
            f"Deadtime = exposure_time - exposure_period = "
            f"{deadtime} must be greater than "
            f"{JUNGFRAU_DEADTIME_S}"
        )
    return deadtime
