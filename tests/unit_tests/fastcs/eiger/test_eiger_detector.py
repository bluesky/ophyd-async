from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.eiger import EigerDetector, EigerTriggerMode
from ophyd_async.testing import assert_has_calls


@pytest.fixture
def detector(RE, tmp_path):
    path_provider = StaticPathProvider(StaticFilenameProvider("filename"), tmp_path)
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", path_provider)

    # Enough to satisfy the odin writer
    set_mock_value(detector.od.fp.writing, True)
    set_mock_value(detector.od.mw.writing, True)
    set_mock_value(detector.detector.bit_depth_image, 16)
    return detector


async def test_prepare_internal_calls_correct_parameters(
    detector: EigerDetector, tmp_path
):
    await detector.prepare(
        TriggerInfo(
            number_of_events=10,
            livetime=0.1,
            trigger=DetectorTrigger.INTERNAL,
        )
    )
    assert_has_calls(
        detector,
        [
            call.detector.trigger_mode.put(EigerTriggerMode.INTERNAL),
            call.detector.nimages.put(10),
            call.detector.count_time.put(0.1),
            call.detector.frame_time.put(0.1),
            call.od.fp.data_datatype.put("uint16"),
            call.od.fp.data_compression.put("BSLZ4"),
            call.od.fp.frames.put(0),
            call.od.fp.process_frames_per_block.put(1000),
            call.od.fp.file_path.put(str(tmp_path)),
            call.od.mw.directory.put(str(tmp_path)),
            call.od.fp.file_prefix.put("filename.h5"),
            call.od.mw.file_prefix.put("filename.h5"),
            call.od.mw.acquisition_id.put("filename.h5"),
            call.od.fp.start_writing.put(None),
        ],
        reset_after=False,
    )


async def test_deadtime_correct(detector: EigerDetector):
    supported_triggers, deadtime = await detector.get_trigger_deadtime()
    assert supported_triggers == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    }
    assert deadtime == 0.0001
