from unittest.mock import AsyncMock, MagicMock

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
    callback_on_mock_put,
    get_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.eiger import EigerDetector


@pytest.fixture
def detector(RE):
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", MagicMock())

    def set_meta_filename_and_id(value, *args, **kwargs):
        set_mock_value(detector.odin.mw.file_prefix, value)
        set_mock_value(detector.odin.mw.acquisition_id, value)

    callback_on_mock_put(detector.odin.fp.file_prefix, set_meta_filename_and_id)

    detector._writer._path_provider.return_value.filename = "filename.h5"  # type: ignore

    set_mock_value(detector.odin.fp.writing, True)
    return detector


async def test_when_prepared_eiger_bit_depth_is_passed_and_set_in_odin(detector):
    detector._controller.arm = AsyncMock()
    expected_datatype = 16
    set_mock_value(detector.drv.detector.bit_depth_image, expected_datatype)

    await detector.prepare(
        TriggerInfo(
            exposure_timeout=None,
            number_of_events=1,
            trigger=DetectorTrigger.INTERNAL,
        )
    )

    # Assert that odin datatype is set to the eiger bit depth during detector prepare
    get_mock_put(detector.odin.fp.data_datatype).assert_called_once_with(
        f"uint{expected_datatype}", wait=True
    )
