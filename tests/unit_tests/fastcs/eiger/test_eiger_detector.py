from pathlib import Path
from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.eiger import EigerDetector, EigerTriggerMode


@pytest.fixture
def detector(RE):
    path_provider = StaticPathProvider(
        StaticFilenameProvider("filename.h5"), Path("/tmp")
    )
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", path_provider)

    def set_meta_filename_and_id(value, *args, **kwargs):
        set_mock_value(detector.od.mw.file_prefix, value)
        set_mock_value(detector.od.mw.acquisition_id, value)

    callback_on_mock_put(detector.od.fp.file_prefix, set_meta_filename_and_id)
    set_mock_value(detector.od.fp.writing, True)
    set_mock_value(detector.detector.bit_depth_image, 16)
    return detector


async def test_prepare_internal_calls_correct_parameters(detector: EigerDetector):
    await detector.prepare(
        TriggerInfo(
            number_of_events=10,
            livetime=0.1,
            trigger=DetectorTrigger.INTERNAL,
        )
    )
    assert list(get_mock(detector).mock_calls) == [
        call.detector.trigger_mode.put(EigerTriggerMode.INTERNAL, wait=True),
        call.detector.nimages.put(10, wait=True),
        call.detector.count_time.put(0.1, wait=True),
        call.detector.frame_time.put(0.1, wait=True),
        call.od.fp.data_datatype.put("uint16", wait=True),
        call.od.fp.data_compression.put("BSLZ4", wait=True),
        call.od.fp.frames.put(0, wait=True),
        call.od.fp.process_frames_per_block.put(1000, wait=True),
        call.od.fp.file_path.put("/tmp", wait=True),
        call.od.mw.directory.put("/tmp", wait=True),
        call.od.fp.file_prefix.put("filename.h5", wait=True),
        call.od.mw.file_prefix.put("filename.h5", wait=True),
        call.od.mw.acquisition_id.put("filename.h5", wait=True),
        call.od.fp.start_writing.put(None, wait=True),
    ]


async def test_deadtime_correct(detector: EigerDetector):
    supported_triggers, deadtime = await detector.get_trigger_deadtime()
    assert supported_triggers == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    }
    assert deadtime == 0.0001
