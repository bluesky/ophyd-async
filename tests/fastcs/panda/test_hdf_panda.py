import os

import pytest

from ophyd_async.core import (
    StaticFilenameProvider,
    StaticPathProvider,
)
from ophyd_async.fastcs.panda import (
    DatasetTable,
    HDFPanda,
    PandaHdf5DatasetType,
)
from ophyd_async.testing import callback_on_mock_put, set_mock_value


@pytest.fixture
async def mock_hdf_panda(tmp_path):
    fp = StaticFilenameProvider("test-panda")
    dp = StaticPathProvider(fp, tmp_path)

    mock_hdf_panda = HDFPanda("HDFPANDA:", path_provider=dp, name="panda")
    await mock_hdf_panda.connect(mock=True)

    def link_function(value: bool, wait: bool = True):
        set_mock_value(mock_hdf_panda.pcap.active, value)

    # Mimic directory exists check that happens normally in the PandA IOC
    def check_dir_exits(value: str, wait: bool = True):
        if os.path.exists(value):
            set_mock_value(mock_hdf_panda.data.directory_exists, True)

    callback_on_mock_put(mock_hdf_panda.pcap.arm, link_function)
    callback_on_mock_put(mock_hdf_panda.data.hdf_directory, check_dir_exits)

    set_mock_value(
        mock_hdf_panda.data.datasets,
        DatasetTable(
            name=["x", "y"],
            dtype=[PandaHdf5DatasetType.UINT_32, PandaHdf5DatasetType.FLOAT_64],
        ),
    )

    yield mock_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(mock_hdf_panda: HDFPanda):
    assert hasattr(mock_hdf_panda._controller, "pcap")
    assert mock_hdf_panda._controller.pcap is mock_hdf_panda.pcap
