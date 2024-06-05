import asyncio
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    SignalR,
    StaticDirectoryProvider,
    set_mock_value,
)
from ophyd_async.epics.areadetector.writers.general_hdffile import _HDFFile
from ophyd_async.epics.pvi import create_children_from_annotations, fill_pvi_entries
from ophyd_async.epics.signal.signal import epics_signal_r
from ophyd_async.panda import CommonPandaBlocks
from ophyd_async.panda.writers._hdf_writer import (
    Capture,
    CaptureSignalWrapper,
    PandaHDFWriter,
    get_capture_signals,
    get_signals_marked_for_capture,
)


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
        mock_panda.block_a.test_capture,
        Capture.MinMaxMean,  # type: ignore[attr-defined]
    )

    set_mock_value(
        mock_panda.block_b.test_capture,
        Capture.No,  # type: ignore[attr-defined]
    )

    return mock_panda


@pytest.fixture
async def mock_writer(tmp_path, mock_panda) -> PandaHDFWriter:
    dir_prov = StaticDirectoryProvider(
        directory_path=str(tmp_path), filename_prefix="", filename_suffix="/data"
    )
    async with DeviceCollector(mock=True):
        writer = PandaHDFWriter(
            prefix="TEST-PANDA",
            directory_provider=dir_prov,
            name_provider=lambda: "test-panda",
            panda_device=mock_panda,
        )

    return writer


async def test_get_capture_signals_gets_all_signals(mock_panda):
    async with DeviceCollector(mock=True):
        mock_panda.test_seq = Device("seq")
        mock_panda.test_seq.seq1_capture = epics_signal_r(
            str, "pva://read_pv_1", name="seq1_capture"
        )
        mock_panda.test_seq.seq2_capture = epics_signal_r(
            str, "pva://read_pv_2", name="seq2_capture"
        )
        await asyncio.gather(
            mock_panda.test_seq.connect(mock=True),
            mock_panda.test_seq.seq1_capture.connect(mock=True),
            mock_panda.test_seq.seq2_capture.connect(mock=True),
        )
    capture_signals = get_capture_signals(mock_panda)
    expected_signals = [
        "block_a.test_capture",
        "block_b.test_capture",
        "test_seq.seq1_capture",
        "test_seq.seq2_capture",
    ]
    for signal in expected_signals:
        assert signal in capture_signals.keys()


async def test_get_signals_marked_for_capture(mock_panda):
    capture_signals = {
        "block_a.test_capture": mock_panda.block_a.test_capture,
        "block_b.test_capture": mock_panda.block_b.test_capture,
    }
    signals_marked_for_capture = await get_signals_marked_for_capture(capture_signals)
    assert len(signals_marked_for_capture) == 1
    assert signals_marked_for_capture["block_a.test"].capture_type == Capture.MinMaxMean


async def test_open_returns_correct_descriptors(mock_writer: PandaHDFWriter):
    assert hasattr(mock_writer.panda_device, "data")
    cap1 = mock_writer.panda_device.block_a.test_capture  # type: ignore[attr-defined]
    cap2 = mock_writer.panda_device.block_b.test_capture  # type: ignore[attr-defined]
    set_mock_value(cap1, Capture.MinMaxMean)
    set_mock_value(cap2, Capture.Value)
    description = await mock_writer.open()  # to make capturing status not time out
    assert len(description) == 4
    for key, entry in description.items():
        assert entry.get("shape") == [1]
        assert entry.get("dtype") == "number"
        assert isinstance(key, str)
        assert "source" in entry
        assert entry.get("external") == "STREAM:"
    expected_datakeys = [
        "test-panda-block_a-test-Min",
        "test-panda-block_a-test-Max",
        "test-panda-block_a-test-Mean",
        "test-panda-block_b-test-Value",
    ]
    for key in expected_datakeys:
        assert key in description


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


async def test_collect_stream_docs(mock_writer: PandaHDFWriter):
    # Give the mock writer datasets
    cap1 = mock_writer.panda_device.block_a.test_capture  # type: ignore[attr-defined]
    cap2 = mock_writer.panda_device.block_b.test_capture  # type: ignore[attr-defined]
    set_mock_value(cap1, Capture.MinMaxMean)
    set_mock_value(cap2, Capture.Value)
    await mock_writer.open()

    [item async for item in mock_writer.collect_stream_docs(1)]
    assert type(mock_writer._file) is _HDFFile
    assert mock_writer._file._last_emitted == 1
    resource_doc = mock_writer._file._bundles[0].stream_resource_doc
    assert resource_doc["data_key"] == "test-panda-block_a-test-Min"
    assert "mock_panda/data.h5" in resource_doc["resource_path"]


async def test_numeric_blocks_correctly_formated(mock_writer: PandaHDFWriter):
    async def get_numeric_signal(_):
        return {
            "device.block.1": CaptureSignalWrapper(
                epics_signal_r(str, "pva://read_pv", name="Capture.Value"),
                Capture.Value,
            )
        }

    with patch(
        "ophyd_async.panda.writers._hdf_writer.get_signals_marked_for_capture",
        get_numeric_signal,
    ):
        assert "test-panda-block-1-Value" in await mock_writer.open()
