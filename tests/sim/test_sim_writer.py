from unittest.mock import patch

import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.sim import PatternGenerator
from ophyd_async.sim.sim_pattern_detector_writer import SimPatternDetectorWriter


@pytest.fixture
async def writer(static_directory_provider) -> SimPatternDetectorWriter:
    async with DeviceCollector(mock=True):
        driver = PatternGenerator()

    return SimPatternDetectorWriter(driver, static_directory_provider, lambda: "NAME")


async def test_correct_descriptor_doc_after_open(writer: SimPatternDetectorWriter):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        descriptor = await writer.open()

    assert descriptor == {
        "NAME": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": (240, 320),
            "dtype": "array",
            "external": "STREAM:",
        },
        "NAME-sum": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": (),
            "dtype": "number",
            "external": "STREAM:",
        },
    }

    await writer.close()


async def test_collect_stream_docs(writer: SimPatternDetectorWriter):
    await writer.open()
    [item async for item in writer.collect_stream_docs(1)]
    assert writer.pattern_generator._handle_for_h5_file
