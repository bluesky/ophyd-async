from pathlib import Path
from unittest.mock import ANY

import numpy as np
import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    SignalR,
    StaticDirectoryProvider,
    set_mock_value,
)
from ophyd_async.epics.pvi import create_children_from_annotations, fill_pvi_entries
from ophyd_async.panda import CommonPandaBlocks
from ophyd_async.panda._table import DatasetTable, PandaHdf5DatasetType
from ophyd_async.panda.writers._hdf_writer import PandaHDFWriter
from ophyd_async.panda.writers._panda_hdf_file import _HDFFile

TABLES = [
    DatasetTable(
        name=np.array([]),
        hdf5_type=[],
    ),
    DatasetTable(
        name=np.array(
            [
                "x",
            ]
        ),
        hdf5_type=[
            PandaHdf5DatasetType.UINT_32,
        ],
    ),
    DatasetTable(
        name=np.array(
            [
                "x",
                "y",
                "y_min",
                "y_max",
            ]
        ),
        hdf5_type=[
            PandaHdf5DatasetType.UINT_32,
            PandaHdf5DatasetType.FLOAT_64,
            PandaHdf5DatasetType.FLOAT_64,
            PandaHdf5DatasetType.FLOAT_64,
        ],
    ),
]


@pytest.fixture
async def panda_t():
    class CaptureBlock(Device):
        test_capture: SignalR

    class Panda(CommonPandaBlocks):
        block_a: CaptureBlock
        block_b: CaptureBlock

        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            create_children_from_annotations(self)
            super().__init__(name)

        async def connect(self, mock: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(
                self, self._prefix + "PVI", timeout=timeout, mock=mock
            )
            await super().connect(mock=mock, timeout=timeout)

    yield Panda


@pytest.fixture
async def mock_panda(panda_t):
    async with DeviceCollector(mock=True):
        mock_panda = panda_t("mock_PANDA", name="mock_panda")

    set_mock_value(
        mock_panda.data.datasets,
        DatasetTable(
            name=np.array([]),
            hdf5_type=[],
        ),
    )

    return mock_panda


@pytest.fixture
async def mock_writer(tmp_path, mock_panda) -> PandaHDFWriter:
    dir_prov = StaticDirectoryProvider(
        directory_path=str(tmp_path), filename_prefix="", filename_suffix="/data"
    )
    async with DeviceCollector(mock=True):
        writer = PandaHDFWriter(
            directory_provider=dir_prov,
            panda_device=mock_panda,
        )

    return writer


@pytest.mark.parametrize("table", TABLES)
async def test_open_returns_correct_descriptors(
    mock_writer: PandaHDFWriter, table: DatasetTable
):
    assert hasattr(mock_writer.panda_device, "data")
    set_mock_value(
        mock_writer.panda_device.data.datasets,
        table,
    )
    description = await mock_writer.open()  # to make capturing status not time out

    for key, entry, expected_key in zip(
        description.keys(), description.values(), table["name"]
    ):
        assert key == expected_key
        assert entry == {
            "source": mock_writer.panda_device.data.hdf_directory.source,
            "shape": [1],
            "dtype": "number",
            "external": "STREAM:",
        }


async def test_open_close_sets_capture(mock_writer: PandaHDFWriter):
    assert isinstance(await mock_writer.open(), dict)
    assert await mock_writer.panda_device.data.capture.get_value()
    await mock_writer.close()
    assert not await mock_writer.panda_device.data.capture.get_value()


async def test_open_sets_file_path_and_name(mock_writer: PandaHDFWriter, tmp_path):
    await mock_writer.open()
    path = await mock_writer.panda_device.data.hdf_directory.get_value()
    assert path == str(tmp_path)
    name = await mock_writer.panda_device.data.hdf_file_name.get_value()
    assert name == "mock_panda/data.h5"


async def test_open_errors_when_multiplier_not_one(mock_writer: PandaHDFWriter):
    with pytest.raises(ValueError):
        await mock_writer.open(2)


async def test_get_indices_written(mock_writer: PandaHDFWriter):
    await mock_writer.open()
    set_mock_value(mock_writer.panda_device.data.num_captured, 4)
    written = await mock_writer.get_indices_written()
    assert written == 4


async def test_wait_for_index(mock_writer: PandaHDFWriter):
    await mock_writer.open()
    set_mock_value(mock_writer.panda_device.data.num_captured, 3)
    await mock_writer.wait_for_index(3, timeout=1)
    set_mock_value(mock_writer.panda_device.data.num_captured, 2)
    with pytest.raises(TimeoutError):
        await mock_writer.wait_for_index(3, timeout=0.1)


@pytest.mark.parametrize("table", TABLES)
async def test_collect_stream_docs(
    mock_writer: PandaHDFWriter,
    tmp_path: Path,
    table: DatasetTable,
):
    # Give the mock writer datasets
    set_mock_value(mock_writer.panda_device.data.datasets, table)

    await mock_writer.open()

    [item async for item in mock_writer.collect_stream_docs(1)]
    assert type(mock_writer._file) is _HDFFile
    assert mock_writer._file._last_emitted == 1
    for i in range(len(table["name"])):
        resource_doc = mock_writer._file._bundles[i].stream_resource_doc
        name = table["name"][i]
        assert resource_doc == {
            "spec": "AD_HDF5_SWMR_SLICE",
            "path_semantics": "posix",
            "root": str(tmp_path),
            "data_key": name,
            "resource_path": str(tmp_path / "mock_panda" / "data.h5"),
            "resource_kwargs": {
                "path": "/" + name,
                "multiplier": 1,
                "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
            },
            "uid": ANY,
        }
        assert resource_doc["data_key"] == name
        assert "mock_panda/data.h5" in resource_doc["resource_path"]
