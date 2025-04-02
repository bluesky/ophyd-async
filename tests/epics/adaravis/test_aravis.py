from unittest.mock import AsyncMock, patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adaravis


@pytest.fixture
def test_adaravis(ad_standard_det_factory) -> adaravis.AravisDetector:
    return ad_standard_det_factory(adaravis.AravisDetector)


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_invariant_with_exposure_time(
    exposure_time: float,
    test_adaravis: adaravis.AravisDetector,
):
    assert test_adaravis._controller.get_deadtime(exposure_time) == 1961e-6


async def test_unsupported_trigger_excepts(test_adaravis: adaravis.AravisDetector):
    with patch(
        "ophyd_async.epics.adcore._hdf_writer.ADHDFWriter.open", new_callable=AsyncMock
    ) as mock_open:
        with pytest.raises(
            ValueError,
            # str(EnumClass.value) handling changed in Python 3.11
            match="ADAravis does not support (DetectorTrigger.)?VARIABLE_GATE",
        ):
            await test_adaravis.prepare(
                TriggerInfo(
                    number_of_triggers=0,
                    trigger=DetectorTrigger.VARIABLE_GATE,
                    deadtime=1,
                    livetime=1,
                    frame_timeout=3,
                )
            )

    mock_open.assert_called_once()
