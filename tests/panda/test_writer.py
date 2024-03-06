import asyncio

import pytest

from ophyd_async.core import (
    Device,
    DeviceCollector,
    SignalR,
    SimSignalBackend,
    StaticDirectoryProvider,
    set_sim_value,
)
from ophyd_async.epics.signal.signal import SignalRW
from ophyd_async.panda import PandA
from ophyd_async.panda.writers import PandaHDFWriter
from ophyd_async.panda.writers.hdf_writer import (
    Capture,
    get_capture_signals,
    get_signals_marked_for_capture,
)


@pytest.fixture
async def sim_panda() -> PandA:
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDAQSRV")
        # TODO check if real signal names end with _capture
        sim_panda.block1 = Device("BLOCK1")
        sim_panda.block2 = Device("BLOCK2")
        sim_panda.block1.test_capture = SignalR(
            backend=SimSignalBackend(str, source="BLOCK1_capture")
        )
        sim_panda.block2.test_capture = SignalR(
            backend=SimSignalBackend(str, source="BLOCK2_capture")
        )
        await asyncio.gather(
            sim_panda.block1.connect(sim=True),
            sim_panda.block2.connect(sim=True),
            sim_panda.connect(sim=True),
        )
        return sim_panda


@pytest.fixture
async def sim_writer(tmp_path, sim_panda: PandA) -> PandaHDFWriter:
    dir_prov = StaticDirectoryProvider(str(tmp_path), "test")
    async with DeviceCollector(sim=True):
        writer = PandaHDFWriter(
            "TEST-PANDA", dir_prov, lambda: "test-panda", panda_device=sim_panda
        )
        writer.hdf5.filepath = SignalRW(
            backend=SimSignalBackend(str, source="TEST-PANDA:HDF5:FilePath")
        )
        writer.hdf5.filename = SignalRW(
            backend=SimSignalBackend(str, source="TEST-PANDA:HDF5:FileName")
        )
        writer.hdf5.numcapture = SignalRW(
            backend=SimSignalBackend(int, source="TEST-PANDA:HDF5:NumCapture")
        )
        writer.hdf5.capture = SignalRW(
            backend=SimSignalBackend(bool, source="TEST-PANDA:HDF5:Capture")
        )
        writer.hdf5.numcaptured = SignalRW(
            backend=SimSignalBackend(int, source="TEST-PANDA:HDF5:NumCaptured")
        )
        writer.hdf5.numrecieved = SignalRW(
            backend=SimSignalBackend(int, source="TEST-PANDA:HDF5:NumRecieved")
        )
        hdf = writer.hdf5
        await asyncio.gather(hdf.filepath.connect(), hdf.filename.connect())

    return writer


async def test_get_capture_signals_gets_all_signals(sim_panda):
    async with DeviceCollector(sim=True):
        sim_panda.test_seq = Device("seq")
        sim_panda.test_seq.seq1_capture = SignalR(
            backend=SimSignalBackend(str, source="seq1_capture")
        )
        sim_panda.test_seq.seq2_capture = SignalR(
            backend=SimSignalBackend(str, source="seq2_capture")
        )
        await asyncio.gather(
            sim_panda.test_seq.connect(),
            sim_panda.test_seq.seq1_capture.connect(),
            sim_panda.test_seq.seq2_capture.connect(),
        )
    capture_signals = get_capture_signals(sim_panda)
    expected_signals = [
        "block1.test_capture",
        "block2.test_capture",
        "test_seq.seq1_capture",
        "test_seq.seq2_capture",
    ]
    for signal in expected_signals:
        assert signal in capture_signals.keys()


async def test_get_signals_marked_for_capture(sim_panda):
    set_sim_value(sim_panda.block1.test_capture, Capture.MinMaxMean)
    set_sim_value(sim_panda.block2.test_capture, Capture.No)
    capture_signals = {
        "block1.test_capture": sim_panda.block1.test_capture,
        "block2.test_capture": sim_panda.block2.test_capture,
    }
    signals_marked_for_capture = await get_signals_marked_for_capture(capture_signals)
    assert len(signals_marked_for_capture) == 1
    assert (
        signals_marked_for_capture["block1.test_capture"]["capture_type"]
        == Capture.MinMaxMean
    )  # TODO does the dict returned by this function still need to contain the signal?


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_open_returns_correct_descriptors(sim_writer: PandaHDFWriter):
    set_sim_value(sim_writer.panda_device.block1.test_capture, Capture.MinMaxMean)
    set_sim_value(sim_writer.panda_device.block2.test_capture, Capture.Value)
    description = await sim_writer.open()  # to make capturing status not time out
    assert len(description) == 2
    for key, entry in description.items():
        if key == "test-panda.block1.test_capture":
            assert entry.get("shape") == [3]
        else:
            assert entry.get("shape") == [1]
            assert entry.get("dtype") == "number"
        assert isinstance(key, str)
        assert "source" in entry

        assert entry.get("external") == "STREAM:"


# @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
# async def test_open_close_sets_capture(sim_writer):
#     await sim_writer.hdf5.capturing.set(1)
#     return_val = await sim_writer.open()  # to make capturing status not time out
#     assert isinstance(return_val, dict)
#     capture = await sim_writer.hdf5.capture.get_value()
#     assert capture is True
#     await sim_writer.hdf5.capturing.set(0)
#     await sim_writer.close()
#     capture = await sim_writer.hdf5.capture.get_value()
#     assert capture is False


# @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
# async def test_open_sets_file_path(sim_writer, tmp_path):
#     path = await sim_writer.hdf5.filepath.get_value()
#     assert path == ""
#     await sim_writer.hdf5.capturing.set(1)  # to make capturing status not time out
#     await sim_writer.open()
#     path = await sim_writer.hdf5.filepath.get_value()
#     assert path == str(tmp_path)
#     name = await sim_writer.hdf5.filename.get_value()
#     assert name == "test.h5"


# @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
# async def test_get_indices_written(sim_writer):
#     written = await sim_writer.get_indices_written()
#     assert written == 0, f"{written} != 0"

#     async def get_twentyfive():
#         return 25

#     with patch("ophyd_async.core.SignalR.get_value", wraps=get_twentyfive):
#         written = await sim_writer.get_indices_written()
#     assert written == 25, f"{written} != 25"


# @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
# async def test_wait_for_index(sim_writer):
#     # usually numwritten_rbv is a SignalR so can't be set from ophyd,
#     # overload with SignalRW for testing
#     await set_and_wait_for_value(sim_writer.hdf5.numwritten_rbv, 25)
#     assert (await sim_writer.hdf5.numwritten_rbv.get_value()) == 25
#     await sim_writer.wait_for_index(25, timeout=1)
#     with pytest.raises(TimeoutError):
#         await sim_writer.wait_for_index(27, timeout=1)


# @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
# async def test_collect_stream_docs(sim_writer):
#     assert sim_writer._file is None

#     [item async for item in sim_writer.collect_stream_docs(1)]
#     assert sim_writer._file


async def test_to_capture():
    # Make sure that _to_capture property holds a dictionary of block names to signals.
    # On connecting or initialising, writer should check all of panda PV's to see if
    # they are being captured, and what kind of capture
    pass
