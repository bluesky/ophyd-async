import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adandor


@pytest.fixture
def test_adandor(ad_standard_det_factory) -> adandor.Andor2Detector:
    return ad_standard_det_factory(adandor.Andor2Detector)


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_from_exposure_time(
    exposure_time: float,
    test_adandor: adandor.Andor2Detector,
):
    assert test_adandor._controller.get_deadtime(exposure_time) == exposure_time + 0.1


async def test_unsupported_trigger_excepts(test_adandor: adandor.Andor2Detector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=("Andor2Controller only supports the following trigger types: .* but"),
    ):
        await test_adandor.prepare(
            TriggerInfo(
                number_of_events=0,
                trigger=DetectorTrigger.VARIABLE_GATE,
                deadtime=1.1,
                livetime=1,
                exposure_timeout=3,
            )
        )
