from unittest.mock import patch
import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.core import StaticDirectoryProvider
from ophyd_async.sim import SimDriver
from ophyd_async.sim.SimPatternDetectorWriter import SimPatternDetectorWriter


@pytest.fixture
async def writer(tmp_path) -> SimPatternDetectorWriter:
    async with DeviceCollector(sim=True):
        driver = SimDriver()
    directory = StaticDirectoryProvider(tmp_path)

    return SimPatternDetectorWriter(driver, directory)


async def test_correct_descriptor_doc_after_open(writer: SimPatternDetectorWriter):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        descriptor = await writer.open()

    assert descriptor == {
        "test": {
            "source": "sim://HDF:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "external": "STREAM:",
        }
    }

    await writer.close()


async def test_collect_stream_docs(writer: SimPatternDetectorWriter):
    assert writer.driver._handle_for_h5_file is None

    [item async for item in writer.collect_stream_docs(1)]
    assert writer.driver._handle_for_h5_file
