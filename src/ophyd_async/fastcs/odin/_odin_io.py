import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DetectorWriter,
    Device,
    DeviceVector,
    NameProvider,
    PathProvider,
    SignalR,
    SignalRW,
    SignalW,
    StrictEnum,
    observe_value,
    set_and_wait_for_other_value,
)
from ophyd_async.fastcs.core import fastcs_connector


class Writing(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class OdinNode(Device):
    writing: SignalR[Writing]


class OdinHdfIO(Device):
    writing: SignalR[Writing]
    config_hdf_write: SignalW[Writing]
    frames_written: SignalR[int]
    config_hdf_frames: SignalW[int]
    dataset_data_dims_0: SignalRW[int]
    dataset_data_dims_1: SignalRW[int]
    dataset_data_chunks_0: SignalRW[int]
    dataset_data_chunks_1: SignalRW[int]
    dataset_data_chunks_2: SignalRW[int]
    config_hdf_file_path: SignalRW[str]
    config_hdf_file_prefix: SignalRW[str]
    dataset_data_datatype: SignalRW[str]
    nodes = DeviceVector[OdinNode]

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        name_provider: NameProvider,
        odin_driver: OdinHdfIO,
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        self._name_provider = name_provider
        super().__init__()

    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=self._name_provider())

        await asyncio.gather(
            self._drv.config_hdf_file_path.set(str(info.directory_path)),
            self._drv.config_hdf_file_prefix.set(info.filename),
            self._drv.dataset_data_datatype.set(
                "uint16"
            ),  # TODO: Get from eiger https://github.com/bluesky/ophyd-async/issues/529
            self._drv.config_hdf_frames.set(0),
        )

        await self._drv.config_hdf_write.set(Writing.ON)

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self._drv.dataset_data_dims_0.get_value(),
            self._drv.dataset_data_dims_1.get_value(),
        )

        return {
            "data": DataKey(
                source=self._drv.config_hdf_file_prefix.source,
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

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
        # TODO: Correctly return stream https://github.com/bluesky/ophyd-async/issues/530
        raise NotImplementedError()

    async def close(self) -> None:
        await set_and_wait_for_other_value(
            self._drv.config_hdf_write, Writing.OFF, self._drv.writing, Writing.OFF
        )
