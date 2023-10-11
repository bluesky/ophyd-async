from ophyd_async.core import DeviceCollector, StaticDirectoryProvider
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF
import pytest
from unittest.mock import patch

class DummyShapeProvider:
    def __init__(self):
        ...

    async def __call__(self):
        return (10, 10)

@pytest.fixture
async def hdf_writer(RE) -> HDFWriter:
    async with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF:")
    
    shape_provider = DummyShapeProvider()
    
    return HDFWriter(hdf, StaticDirectoryProvider("some_path", "some_prefix"), lambda: "test", shape_provider)


async def test_correct_descriptor_doc_after_open(hdf_writer: HDFWriter):
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer.open()

    assert descriptor == {"test": {'source': 'sim://HDF:FullFileName_RBV', 'shape': (10, 10), 'dtype': 'array', 'external': 'STREAM:'}}

async def test_collect_stream_docs(hdf_writer: HDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file
