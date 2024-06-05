from typing import Sequence
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DeviceCollector,
    ShapeProvider,
    StaticDirectoryProvider,
    set_mock_value,
)
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class DummyShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self) -> Sequence[int]:
        return (10, 10)


@pytest.fixture
async def hdf_writer(RE) -> HDFWriter:
    async with DeviceCollector(mock=True):
        hdf = NDFileHDF("HDF:")

    return HDFWriter(
        hdf,
        StaticDirectoryProvider("some_path", "some_prefix"),
        name_provider=lambda: "test",
        shape_provider=DummyShapeProvider(),
    )


async def test_correct_descriptor_doc_after_open(hdf_writer: HDFWriter):
    set_mock_value(hdf_writer.hdf.file_path_exists, True)
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer.open()

    assert descriptor == {
        "test": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "external": "STREAM:",
        }
    }

    await hdf_writer.close()


async def test_collect_stream_docs(hdf_writer: HDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file
