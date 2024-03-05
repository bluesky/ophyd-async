from unittest.mock import patch

import pytest
from bluesky.protocols import Descriptor

from ophyd_async.core import (
    DeviceCollector,
    SimSignalBackend,
    StaticDirectoryProvider,
    set_and_wait_for_value,
)
from ophyd_async.epics.signal.signal import SignalRW
from ophyd_async.panda.writers import PandaHDFWriter


@pytest.fixture
async def sim_writer(tmp_path) -> PandaHDFWriter:
    dir_prov = StaticDirectoryProvider(str(tmp_path), "test")
    async with DeviceCollector(sim=True):
        writer = PandaHDFWriter("TEST-PANDA", dir_prov, lambda: "test-panda")
        writer.hdf5.filepath = SignalRW(
            backend=SimSignalBackend(str, source="TEST-PANDA:HDF5:FilePath")
        )
        writer.hdf5.filename = SignalRW(
            backend=SimSignalBackend(str, source="TEST-PANDA:HDF5:FileName")
        )
        writer.hdf5.fullfilename = SignalRW(
            backend=SimSignalBackend(str, source="TEST-PANDA:HDF5:FullFileName")
        )
        writer.hdf5.numcapture = SignalRW(
            backend=SimSignalBackend(int, source="TEST-PANDA:HDF5:NumCapture")
        )
        writer.hdf5.capture = SignalRW(
            backend=SimSignalBackend(bool, source="TEST-PANDA:HDF5:Capture")
        )
        writer.hdf5.capturing = SignalRW(
            backend=SimSignalBackend(bool, source="TEST-PANDA:HDF5:Capturing")
        )
        writer.hdf5.flushnow = SignalRW(
            backend=SimSignalBackend(bool, source="TEST-PANDA:HDF5:FlushNow")
        )
        writer.hdf5.numwritten_rbv = SignalRW(
            backend=SimSignalBackend(int, source="TEST-PANDA:HDF5:NumWritten_RBV")
        )
        await writer.connect(sim=True)
    return writer


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_returns_descriptors(sim_writer: PandaHDFWriter):
    await sim_writer.hdf5.capturing.set(1)
    description = await sim_writer.open()  # to make capturing status not time out
    assert isinstance(description, dict)
    for key, entry in description.items():
        assert isinstance(key, str)
        assert isinstance(entry, Descriptor)
        assert "source" in entry
        assert entry.get("dtype") == "number"
        assert entry.get("external") == "STREAM:"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_close_sets_capture(sim_writer):
    await sim_writer.hdf5.capturing.set(1)
    return_val = await sim_writer.open()  # to make capturing status not time out
    assert isinstance(return_val, dict)
    capture = await sim_writer.hdf5.capture.get_value()
    assert capture is True
    await sim_writer.hdf5.capturing.set(0)
    await sim_writer.close()
    capture = await sim_writer.hdf5.capture.get_value()
    assert capture is False


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_sets_file_path(sim_writer, tmp_path):
    path = await sim_writer.hdf5.filepath.get_value()
    assert path == ""
    await sim_writer.hdf5.capturing.set(1)  # to make capturing status not time out
    await sim_writer.open()
    path = await sim_writer.hdf5.filepath.get_value()
    assert path == str(tmp_path)
    name = await sim_writer.hdf5.filename.get_value()
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
    # usually numwritten_rbv is a SignalR so can't be set from ophyd,
    # overload with SignalRW for testing
    await set_and_wait_for_value(sim_writer.hdf5.numwritten_rbv, 25)
    assert (await sim_writer.hdf5.numwritten_rbv.get_value()) == 25
    await sim_writer.wait_for_index(25, timeout=1)
    with pytest.raises(TimeoutError):
        await sim_writer.wait_for_index(27, timeout=1)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_collect_stream_docs(sim_writer):
    assert sim_writer._file is None

    [item async for item in sim_writer.collect_stream_docs(1)]
    assert sim_writer._file


async def test_to_capture():
    # Make sure that _to_capture property holds a dictionary of block names to signals.
    # On connecting or initialising, writer should check all of panda PV's to see if
    # they are being captured, and what kind of capture
    pass
