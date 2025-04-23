from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, init_devices
from ophyd_async.fastcs.eiger import EigerDetector, EigerTriggerInfo
from ophyd_async.testing import get_mock_put, set_mock_value


@pytest.fixture
def detector(RE):
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", MagicMock())
    set_mock_value(detector.odin.meta_active, "Active")
    set_mock_value(detector.odin.capture_rbv, "Capturing")
    set_mock_value(detector.odin.meta_writing, "Writing")
    return detector


async def test_when_prepared_with_energy_then_energy_set_on_detector(detector):
    detector._controller.arm = AsyncMock()
    await detector.prepare(
        EigerTriggerInfo(
            exposure_timeout=None,
            number_of_events=1,
            trigger=DetectorTrigger.INTERNAL,
            energy_ev=10000,
        )
    )

    get_mock_put(detector.drv.detector.photon_energy).assert_called_once_with(
        10000, wait=ANY
    )
