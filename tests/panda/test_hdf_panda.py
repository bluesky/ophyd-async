import time
from typing import AsyncGenerator, AsyncIterator, Dict, Optional, Sequence

import pytest
from bluesky.protocols import Descriptor, StreamAsset
from event_model import ComposeStreamResourceBundle, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    DeviceCollector,
    SignalRW,
    SimSignalBackend,
    observe_value,
)
from ophyd_async.panda import HDFPandA, PandaPcapController


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = SignalRW(backend=SimSignalBackend(int, source="test"))
        self._shape = shape
        self._name = name
        self._file: Optional[ComposeStreamResourceBundle] = None
        self._last_emitted = 0
        self.index = 0

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        return {
            self._name: Descriptor(
                source="sim://some-source",
                shape=self._shape,
                dtype="number",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        num_captured: int
        async for num_captured in observe_value(self.dummy_signal, timeout):
            yield num_captured

    async def get_indices_written(self) -> int:
        return self.index

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        if indices_written:
            if not self._file:
                self._file = compose_stream_resource(
                    spec="AD_HDF5_SWMR_SLICE",
                    root="/",
                    data_key=self._name,
                    resource_path="",
                    resource_kwargs={
                        "path": "",
                        "multiplier": 1,
                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                    },
                )
                yield "stream_resource", self._file.stream_resource_doc

            if indices_written >= self._last_emitted:
                indices = dict(
                    start=self._last_emitted,
                    stop=indices_written,
                )
                self._last_emitted = indices_written
                self._last_flush = time.monotonic()
                yield "stream_datum", self._file.compose_stream_datum(indices)

    async def close(self) -> None:
        self._file = None


@pytest.fixture
async def sim_hdf_panda():
    controller = PandaPcapController()
    writer = DummyWriter("dummy", (1, 1))
    async with DeviceCollector(sim=True):
        sim_hdf_panda = HDFPandA("HDFPANDA:", controller, writer, name="HDFPandA")
    yield sim_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(sim_hdf_panda: HDFPandA):
    assert hasattr(sim_hdf_panda.controller, "pcap")
    assert sim_hdf_panda.controller.pcap == sim_hdf_panda.pcap
