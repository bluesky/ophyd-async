from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.xspress import (
    XspressDetector,
    XspressTriggerInfo,
)
from ophyd_async.testing import assert_has_calls


@pytest.fixture
def detector(RE, tmp_path):
    path_provider = StaticPathProvider(StaticFilenameProvider("filename"), tmp_path)
    with init_devices(mock=True):
        detector = XspressDetector("XSP", path_provider)

    # Enough to satisfy the odin writer
    set_mock_value(detector.od.writing, True)
    return detector


async def test_prepare_internal_calls_correct_parameters(
    detector: XspressDetector, tmp_path
):
    # Need to mock this value as it's a summary of the datsets chunk_0
    set_mock_value(detector.od.fp.data_chunks_0, 10)
    await detector.prepare(
        XspressTriggerInfo(
            number_of_events=100,
            livetime=0.1,
            trigger=DetectorTrigger.INTERNAL,
            chunk=10,
        )
    )
    assert_has_calls(
        detector,
        [
            call.od.file_prefix.put("filename"),
            call.od.fp.chunks.put(10),
            call.xspress.trigger_mode.put(2),
            call.xspress.num_images.put(100),
            call.xspress.exposure_time.put(0.1),
            call.od.fp.data_datatype.put("uint32"),
            call.od.fp.data_compression.put("blosc"),
            call.od.fp.frames.put(0),
            call.od.fp.process_frames_per_block.put(1000),
            call.od.file_path.put(str(tmp_path)),
            call.od.fp.start_writing.put(None),
        ],
        reset_after=False,
    )
