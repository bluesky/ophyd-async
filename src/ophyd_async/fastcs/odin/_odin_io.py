import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DetectorWriter,
    Device,
    FilenameProvider,
    PathProvider,
    SignalR,
    SignalRW,
    StrictEnum,
    observe_value,
    set_and_wait_for_value,
)
from ophyd_async.fastcs.core import fastcs_connector


class OdinWriting(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class OdinHdfIO(Device):
    config_hdf_write: SignalRW[OdinWriting]
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

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        odin_driver: OdinHdfIO,
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=name)
        self._exposures_per_event = exposures_per_event

        await asyncio.gather(
            self._drv.file_path.set(str(info.directory_path)),
            self._drv.file_prefix.set(info.filename),
            self._drv.data_datatype.set(
                "UInt16"
            ),  # TODO: Get from eiger https://github.com/bluesky/ophyd-async/issues/529
            self._drv.frames.set(0),
        )

        await self._drv.config_hdf_write.set(OdinWriting.ON)

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self._drv.data_dims_0.get_value(),
            self._drv.data_dims_1.get_value(),
        )

        return {
            "data": DataKey(
                source=self._drv.file_prefix.source,
                shape=list(data_shape),
                dtype="array",
                # TODO: Use correct type based on eiger https://github.com/bluesky/ophyd-async/issues/529
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self._drv.frames_written, timeout):
            yield num_captured

    async def get_indices_written(self) -> int:
        return await self._drv.frames_written.get_value()

    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: Correctly return stream https://github.com/bluesky/ophyd-async/issues/530
        raise NotImplementedError()

    async def close(self) -> None:
        await set_and_wait_for_value(self._drv.config_hdf_write, OdinWriting.OFF)
