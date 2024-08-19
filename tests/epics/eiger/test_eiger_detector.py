from unittest.mock import MagicMock

from ophyd_async.core import DeviceCollector
from ophyd_async.epics.eiger import EigerDetector


def test_when_detector_initialised_then_driver_and_odin_have_expected_prefixes(RE):
    with DeviceCollector(mock=True):
        detector = EigerDetector("BL03I", MagicMock())

    assert "BL03I-EA-EIGER-01:" in detector.drv.arm.source
    assert "BL03I-EA-ODIN-01:FP:" in detector.odin.acquisition_id.source
