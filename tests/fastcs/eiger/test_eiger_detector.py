from unittest.mock import AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, TriggerInfo, init_devices
from ophyd_async.fastcs.eiger import EigerDetector
from ophyd_async.testing import get_mock_put, set_mock_value


@pytest.fixture
def detector(RE):
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", MagicMock())
    set_mock_value(detector.odin.meta_active, "Active")
    set_mock_value(detector.odin.capture_rbv, "Capturing")
    set_mock_value(detector.odin.meta_writing, "Writing")
    return detector


async def test_when_prepared_eiger_bit_depth_is_passed_and_set_in_odin(detector):
    detector._controller.arm = AsyncMock()
    expected_datatype = 16
    set_mock_value(detector.drv.detector.bit_depth_readout, expected_datatype)

    await detector.prepare(
        TriggerInfo(
            exposure_timeout=None,
            number_of_events=1,
            trigger=DetectorTrigger.INTERNAL,
        )
    )

    # Assert that odin datatype is set to the eiger bit depth during detector prepare
    get_mock_put(detector.odin.data_type).assert_called_once_with(
        f"UInt{expected_datatype}", wait=True
    )
