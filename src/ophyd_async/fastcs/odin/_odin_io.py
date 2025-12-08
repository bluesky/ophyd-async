import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    PathProvider,
    Reference,
    SignalR,
    SignalRW,
    SignalX,
    observe_value,
    wait_for_value,
)
from ophyd_async.fastcs.core import fastcs_connector


class MedaWriterIO(Device):
    stop: SignalX
    file_prefix: SignalRW[str]
    directory: SignalRW[str]
    acquisition_id: SignalRW[str]
    writing: SignalR[bool]


class FrameProcessorIO(Device):
    start_writing: SignalX
    stop_writing: SignalX
    writing: SignalR[bool]
    frames_written: SignalR[int]
    frames: SignalRW[int]
    data_dims_0: SignalRW[int]
    data_dims_1: SignalRW[int]
    data_chunks_0: SignalRW[int]
    data_chunks_1: SignalRW[int]
    data_chunks_2: SignalRW[int]
    file_path: SignalRW[str]
    file_prefix: SignalRW[str]
    data_datatype: SignalRW[str]
    data_compression: SignalRW[str]


class OdinHdfIO(Device):
    fp: FrameProcessorIO
    mw: MedaWriterIO

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        odin_driver: OdinHdfIO,
        detector_bit_depth: SignalR[int],
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        self._detector_bit_depth = Reference(detector_bit_depth)
        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=name)
        self._exposures_per_event = exposures_per_event

        await asyncio.gather(
            self._drv.fp.data_datatype.set(
                f"uint{await self._detector_bit_depth().get_value()}"
            ),
            self._drv.fp.data_compression.set("BSLZ4"),
            self._drv.fp.frames.set(exposures_per_event),
            self._drv.fp.file_path.set(str(info.directory_path)),
            self._drv.mw.directory.set(str(info.directory_path)),
            self._drv.fp.file_prefix.set(info.filename),
            self._drv.mw.file_prefix.set(info.filename),
            self._drv.mw.acquisition_id.set(info.filename),
        )

        await self._drv.fp.start_writing.trigger(wait=True)

        await asyncio.gather(
            wait_for_value(self._drv.fp.writing, True, timeout=DEFAULT_TIMEOUT),
        )

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self._drv.fp.data_dims_0.get_value(), self._drv.fp.data_dims_1.get_value()
        )

        return {
            "data": DataKey(
                source=self._drv.fp.file_prefix.source,
                shape=[self._exposures_per_event, *data_shape],
                dtype="array",
                # TODO: Use correct type based on eiger https://github.com/bluesky/ophyd-async/issues/529
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self._drv.fp.frames_written, timeout):
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        return (
            await self._drv.fp.frames_written.get_value() // self._exposures_per_event
        )

    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: Correctly return stream https://github.com/bluesky/ophyd-async/issues/530
        raise NotImplementedError()

    async def close(self) -> None:
        await asyncio.gather(
            self._drv.fp.stop_writing.trigger(wait=True),
            self._drv.mw.stop.trigger(wait=True),
        )
