import asyncio
import logging
import os
from pathlib import Path
from unittest.mock import ANY

import pytest

from ophyd_async.core import (
    Device,
    HDFDocumentComposer,
    SignalR,
    StaticFilenameProvider,
    StaticPathProvider,
    init_devices,
)
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    DatasetTable,
    PandaHdf5DatasetType,
    PandaHDFWriter,
)
from ophyd_async.testing import callback_on_mock_put, set_mock_value

PANDA_DETECTOR_NAME = "mock_panda"

TABLES = [
    DatasetTable(
        name=[],
        dtype=[],
    ),
    DatasetTable(
        name=["x"],
        dtype=[PandaHdf5DatasetType.UINT_32],
    ),
    DatasetTable(
        name=[
            "x",
            "y",
            "y_min",
            "y_max",
        ],
        dtype=[
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
        test_capture: SignalR[float]

    class Panda(CommonPandaBlocks):
        block_a: CaptureBlock
        block_b: CaptureBlock

        def __init__(self, uri: str, name: str = ""):
            super().__init__(name=name, connector=fastcs_connector(self, uri))

    yield Panda


@pytest.fixture
async def mock_panda(panda_t):
    async with init_devices(mock=True):
        mock_panda = panda_t("mock_PANDA", name="mock_panda")

    # Mimic directory exists check that happens normally in the PandA IOC
    def check_dir_exits(value, **kwargs):
        if os.path.exists(os.path.abspath(os.path.dirname(value))):
            set_mock_value(mock_panda.data.directory_exists, 1)

    # Assume directory exists
    callback_on_mock_put(mock_panda.data.hdf_directory, check_dir_exits)

    set_mock_value(
        mock_panda.data.datasets,
        DatasetTable(
            name=[],
            dtype=[],
        ),
    )

    return mock_panda


@pytest.fixture
async def mock_writer(tmp_path, mock_panda) -> PandaHDFWriter:
    fp = StaticFilenameProvider("data")
    dp = StaticPathProvider(fp, tmp_path / mock_panda.name, create_dir_depth=-1)
    async with init_devices(mock=True):
        writer = PandaHDFWriter(
            path_provider=dp,
            panda_data_block=mock_panda.data,
        )

    return writer


@pytest.mark.parametrize("table", TABLES)
async def test_open_returns_correct_descriptors(
    mock_writer: PandaHDFWriter, table: DatasetTable, caplog
):
    assert hasattr(mock_writer, "panda_data_block")
    set_mock_value(
        mock_writer.panda_data_block.datasets,
        table,
    )

    with caplog.at_level(logging.WARNING):
        description = await mock_writer.open(
            PANDA_DETECTOR_NAME
        )  # to make capturing status not time out

        # Check if empty datasets table leads to warning log message
        if len(table.name) == 0:
            assert "DATASETS table is empty!" in caplog.text

    for key, entry, expected_key in zip(
        description.keys(), description.values(), table.name, strict=False
    ):
        assert key == expected_key
        assert entry == {
            "source": mock_writer.panda_data_block.hdf_directory.source,
            "shape": [],
            "dtype": "number",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
        }


async def test_open_close_sets_capture(mock_writer: PandaHDFWriter):
    assert isinstance(await mock_writer.open(PANDA_DETECTOR_NAME), dict)
    assert await mock_writer.panda_data_block.capture.get_value()
    await mock_writer.close()
    assert not await mock_writer.panda_data_block.capture.get_value()


async def test_open_sets_file_path_and_name(mock_writer: PandaHDFWriter, tmp_path):
    await mock_writer.open(PANDA_DETECTOR_NAME)
    path = await mock_writer.panda_data_block.hdf_directory.get_value()
    assert path == str(tmp_path / PANDA_DETECTOR_NAME)
    name = await mock_writer.panda_data_block.hdf_file_name.get_value()
    assert name == "data.h5"


async def test_get_indices_written(mock_writer: PandaHDFWriter):
    await mock_writer.open(PANDA_DETECTOR_NAME)
    set_mock_value(mock_writer.panda_data_block.num_captured, 4)
    written = await mock_writer.get_indices_written()
    assert written == 4


@pytest.mark.parametrize("exposures_per_event", [1, 2, 11])
async def test_wait_for_index(mock_writer: PandaHDFWriter, exposures_per_event: int):
    await mock_writer.open(PANDA_DETECTOR_NAME, exposures_per_event=exposures_per_event)
    set_mock_value(mock_writer.panda_data_block.num_captured, 3 * exposures_per_event)
    await mock_writer.wait_for_index(3, timeout=1)
    set_mock_value(mock_writer.panda_data_block.num_captured, 2 * exposures_per_event)
    with pytest.raises(asyncio.TimeoutError):
        await mock_writer.wait_for_index(3, timeout=0.1)


@pytest.mark.parametrize("table", TABLES)
async def test_collect_stream_docs(
    mock_writer: PandaHDFWriter,
    tmp_path: Path,
    table: DatasetTable,
):
    # Give the mock writer datasets
    set_mock_value(mock_writer.panda_data_block.datasets, table)

    await mock_writer.open(PANDA_DETECTOR_NAME)

    def assert_resource_document(name, resource_doc):
        assert resource_doc == {
            "uid": ANY,
            "data_key": name,
            "mimetype": "application/x-hdf5",
            "uri": "file://localhost/"
            + (tmp_path / "mock_panda" / "data.h5").as_posix().lstrip("/"),
            "parameters": {
                "dataset": f"/{name}",
                "chunk_shape": (1024,),
            },
        }

        # URI will always use '/'
        assert "mock_panda/data.h5" in resource_doc["uri"]

    [item async for item in mock_writer.collect_stream_docs(PANDA_DETECTOR_NAME, 1)]
    assert type(mock_writer._composer) is HDFDocumentComposer
    assert mock_writer._composer._last_emitted == 1

    for i in range(len(table.name)):
        resource_doc = mock_writer._composer._bundles[i].stream_resource_doc
        name = table.name[i]

        assert_resource_document(name=name, resource_doc=resource_doc)

        assert resource_doc["data_key"] == name


async def test_oserror_when_hdf_dir_does_not_exist(tmp_path, mock_panda):
    fp = StaticFilenameProvider("data")
    dp = StaticPathProvider(
        fp, tmp_path / mock_panda.name / "extra" / "dirs", create_dir_depth=-1
    )
    async with init_devices(mock=True):
        writer = PandaHDFWriter(
            path_provider=dp,
            panda_data_block=mock_panda.data,
        )

    with pytest.raises(OSError):
        await writer.open(PANDA_DETECTOR_NAME)
