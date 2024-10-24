from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector, get_mock_put
from ophyd_async.epics.eiger import EigerDetector, EigerTriggerInfo


@pytest.fixture
def detector(RE):
    with DeviceCollector(mock=True):
        detector = EigerDetector("BL03I", MagicMock())
    return detector


def test_when_detector_initialised_then_driver_and_odin_have_expected_prefixes(
    detector,
):
    assert "BL03I-EA-EIGER-01:" in detector.drv.arm.source
    assert "BL03I-EA-ODIN-01:FP:" in detector.odin.acquisition_id.source


async def test_when_prepared_with_energy_then_energy_set_on_detector(detector):
    detector.controller.arm = AsyncMock()
    await detector.prepare(
        EigerTriggerInfo(
            frame_timeout=None,
            number_of_triggers=1,
            trigger=DetectorTrigger.internal,
            deadtime=None,
            livetime=None,
            energy_ev=10000,
        )
    )

    get_mock_put(detector.drv.photon_energy).assert_called_once_with(
        10000, wait=ANY, timeout=ANY
    )
