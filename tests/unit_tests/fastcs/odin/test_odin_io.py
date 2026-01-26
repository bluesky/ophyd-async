import asyncio
from pathlib import Path
from unittest.mock import call

import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    StandardDetector,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
    soft_signal_rw,
)
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.odin import OdinDataLogic, OdinIO
from ophyd_async.testing import assert_has_calls

BIT_DEPTH = 16


class OdinDet(StandardDetector):
    def __init__(self, tmp_path: Path, name="", connector=None):
        path_provider = StaticPathProvider(StaticFilenameProvider("filename"), tmp_path)
        self.odin = OdinIO(connector=fastcs_connector("PREFIX:"))
        self.bit_depth = soft_signal_rw(int, BIT_DEPTH)
        self.add_logics(OdinDataLogic(path_provider, self.odin, self.bit_depth))
        super().__init__(name, connector)


@pytest.fixture
def odin_det(RE: RunEngine, tmp_path) -> OdinDet:
    with init_devices(mock=True):
        det = OdinDet(tmp_path)
    return det


async def test_describe_gives_detector_shape(odin_det: OdinDet, tmp_path):
    set_mock_value(odin_det.odin.fp.writing, True)
    set_mock_value(odin_det.odin.mw.writing, True)
    set_mock_value(odin_det.odin.fp.data_dims_1, 1024)
    set_mock_value(odin_det.odin.fp.data_dims_0, 768)
    await odin_det.prepare(TriggerInfo())
    description = await odin_det.describe()
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
            "shape": [
                1,
                768,
                1024,
            ],
            "source": f"file://localhost{tmp_path.as_posix()}/filename.h5",
        },
    }


async def test_when_closed_then_data_capture_turned_off(odin_det: OdinDet):
    await odin_det.unstage()
    assert_has_calls(
        odin_det,
        [
            call.odin.fp.stop_writing.put(None, wait=True),
            call.odin.mw.stop.put(None, wait=True),
        ],
    )


async def test_wait_for_active_and_file_names_before_capture_then_wait_for_writing(
    odin_det: OdinDet, tmp_path
):
    odin: OdinIO = odin_det.odin
    ev = asyncio.Event()
    callback_on_mock_put(odin_det.odin.fp.start_writing, lambda v, wait=True: ev.set())
    # Start it preparing
    status = odin_det.prepare(TriggerInfo(number_of_events=15))
    # Wait for start_writing to be called
    async with asyncio.timeout(1):
        await ev.wait()
    # Check it isn't done yet, but has the right calls
    assert not status.done
    assert_has_calls(
        odin,
        [
            call.fp.data_datatype.put("uint16", wait=True),
            call.fp.data_compression.put("BSLZ4", wait=True),
            call.fp.frames.put(0, wait=True),
            call.fp.process_frames_per_block.put(1000, wait=True),
            call.fp.file_path.put(str(tmp_path), wait=True),
            call.mw.directory.put(str(tmp_path), wait=True),
            call.fp.file_prefix.put("filename.h5", wait=True),
            call.mw.file_prefix.put("filename.h5", wait=True),
            call.mw.acquisition_id.put("filename.h5", wait=True),
            call.fp.start_writing.put(None, wait=True),
        ],
    )
    # Set the filewriters going
    set_mock_value(odin.fp.writing, True)
    set_mock_value(odin.mw.writing, True)
    # Check we are done now, and no additional calls
    async with asyncio.timeout(1):
        await status
    assert status.done
    assert_has_calls(odin, [])


@pytest.mark.timeout(15)
async def test_hinted_fields(odin_det: OdinDet):
    set_mock_value(odin_det.odin.fp.writing, True)
    set_mock_value(odin_det.odin.mw.writing, True)
    await odin_det.prepare(TriggerInfo())
    assert odin_det.hints == {"fields": ["det"]}
