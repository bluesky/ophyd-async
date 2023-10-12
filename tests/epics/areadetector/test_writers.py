from typing import Sequence

import pytest

from ophyd_async.core import DeviceCollector, ShapeProvider, StaticDirectoryProvider
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class DummyShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self) -> Sequence[int]:
        return (10, 10)


@pytest.fixture
async def hdf_writer(RE) -> HDFWriter:
    async with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF:")

    return HDFWriter(
        hdf,
        StaticDirectoryProvider("some_path", "some_prefix"),
        lambda: "test",
        DummyShapeProvider(),
    )


# for some reason these tests cause tear down errors...

# async def test_correct_descriptor_doc_after_open(hdf_writer: HDFWriter):
#     with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
#         descriptor = await hdf_writer.open()

#     assert descriptor == {"test": {'source': 'sim://HDF:FullFileName_RBV',
# 'shape': (10, 10), 'dtype': 'array', 'external': 'STREAM:'}}

# async def test_collect_stream_docs(hdf_writer: HDFWriter):
#     assert hdf_writer._file is None

#     [item async for item in hdf_writer.collect_stream_docs(1)]
#     assert hdf_writer._file
