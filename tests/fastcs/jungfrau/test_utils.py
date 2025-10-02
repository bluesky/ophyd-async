from ophyd_async.core import DetectorTrigger, TriggerInfo
from ophyd_async.fastcs.jungfrau import (
    JUNGFRAU_DEADTIME_S,
    create_jungfrau_external_triggering_info,
    create_jungfrau_internal_triggering_info,
    create_jungfrau_pedestal_triggering_info,
)


def test_create_jungfrau_internal_triggering_info():
    assert create_jungfrau_internal_triggering_info(5, 1) == TriggerInfo(
        number_of_events=1,
        deadtime=0,
        livetime=1,
        exposures_per_event=5,
    )


def test_create_jungfrau_external_triggering_info():
    assert create_jungfrau_external_triggering_info(
        total_triggers=5,
        exposure_time_s=0.01,
    ) == TriggerInfo(
        number_of_events=5,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        livetime=0.01,
        deadtime=JUNGFRAU_DEADTIME_S,
    )


def test_create_external_triggering_info_regular_deadtime_if_period_not_specified():
    assert create_jungfrau_external_triggering_info(
        total_triggers=5,
        exposure_time_s=0.01,
    ) == TriggerInfo(
        number_of_events=5,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=JUNGFRAU_DEADTIME_S,
        livetime=0.01,
    )


async def test_create_jungfrau_pedestal_triggering_info():
    assert create_jungfrau_pedestal_triggering_info(
        exposure_time_s=0.01, pedestal_frames=5, pedestal_loops=10
    ) == TriggerInfo(
        trigger=DetectorTrigger.INTERNAL,
        number_of_events=20,
        exposures_per_event=5,
        livetime=0.01,
    )
