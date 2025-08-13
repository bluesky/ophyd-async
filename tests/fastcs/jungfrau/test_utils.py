import pytest

from ophyd_async.core import DetectorTrigger, TriggerInfo
from ophyd_async.fastcs.jungfrau import (
    create_jungfrau_external_triggering_info,
    create_jungfrau_internal_triggering_info,
)
from ophyd_async.fastcs.jungfrau._utils import (
    _validate_then_get_deadtime,  # noqa: PLC2701
)


def test_validate_then_get_deadtime():
    with pytest.raises(ValueError):
        _validate_then_get_deadtime(1, 0.5)
    assert _validate_then_get_deadtime(1, 2) == 1


def test_create_jungfrau_internal_triggering_info():
    assert create_jungfrau_internal_triggering_info(5, 1, 2) == TriggerInfo(
        number_of_events=1, deadtime=1, livetime=1, exposures_per_event=5
    )


def test_create_jungfrau_external_triggering_info():
    assert create_jungfrau_external_triggering_info(
        total_triggers=5,
        frames_per_trigger=5,
        exposure_time_s=0.01,
        period_between_frames_s=0.02,
    ) == TriggerInfo(
        number_of_events=5,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=0.01,
        livetime=0.01,
        exposures_per_event=5,
    )
