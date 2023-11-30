from unittest.mock import patch

import pytest
from bluesky.protocols import Descriptor

from ophyd_async.core import (
    DeviceCollector,
    StaticDirectoryProvider,
    set_and_wait_for_value,
)
from ophyd_async.epics.signal.signal import SignalR, epics_signal_rw
from ophyd_async.panda.writers.hdf_writer import PandaHDFWriter
from ophyd_async.panda.writers.panda_hdf import PandaHDF


@pytest.fixture
async def sim_writer(tmp_path) -> PandaHDFWriter:
    dir_prov = StaticDirectoryProvider(str(tmp_path), "test")
    async with DeviceCollector(sim=True):
        hdf = PandaHDF("TEST-PANDA")
        writer = PandaHDFWriter(hdf, dir_prov, lambda: "test-panda")
    return writer


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_returns_descriptors(sim_writer):
    description = await sim_writer.open()
    assert isinstance(description, dict)
    for key, entry in description.items():
        assert isinstance(key, str)
        assert isinstance(entry, Descriptor)
        assert "source" in entry
        assert entry.get("dtype") == "number"
        assert entry.get("external") == "STREAM:"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_close_sets_capture(sim_writer):
    return_val = await sim_writer.open()
    assert isinstance(return_val, dict)
    capturing = await sim_writer.hdf.capture.get_value()
    assert capturing is True
    await sim_writer.close()
    capturing = await sim_writer.hdf.capture.get_value()
    assert capturing is False


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_sets_file_path(sim_writer, tmp_path):
    path = await sim_writer.hdf.file_path.get_value()
    assert path == ""
    await sim_writer.open()
    path = await sim_writer.hdf.file_path.get_value()
    assert path == str(tmp_path)
    name = await sim_writer.hdf.file_name.get_value()
    assert name == "test.h5"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_get_indices_written(sim_writer):
    written = await sim_writer.get_indices_written()
    assert written == 0, f"{written} != 0"

    async def get_twentyfive():
        return 25

    with patch("ophyd_async.core.SignalR.get_value", wraps=get_twentyfive):
        written = await sim_writer.get_indices_written()
    assert written == 25, f"{written} != 25"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_wait_for_index(sim_writer):
    assert type(sim_writer.hdf.num_written) is SignalR
    # usually num_written is a SignalR so can't be set from ophyd,
    # overload with SignalRW for testing
    sim_writer.hdf.num_written = epics_signal_rw(int, "TEST-PANDA:HDF5:NumWritten")
    await sim_writer.hdf.num_written.connect(sim=True)
    await set_and_wait_for_value(sim_writer.hdf.num_written, 25)
    assert (await sim_writer.hdf.num_written.get_value()) == 25
    await sim_writer.wait_for_index(25, timeout=1)
    with pytest.raises(TimeoutError):
        await sim_writer.wait_for_index(27, timeout=1)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_collect_stream_docs(sim_writer):
    assert sim_writer._file is None

    [item async for item in sim_writer.collect_stream_docs(1)]
    assert sim_writer._file
