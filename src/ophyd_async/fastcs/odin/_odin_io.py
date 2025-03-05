import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    DeviceVector,
    NameProvider,
    PathProvider,
    SignalR,
    SignalRW,
    StrictEnum,
    observe_value,
    set_and_wait_for_value,
)
from ophyd_async.fastcs.core import fastcs_connector


class Writing(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class OdinNode(Device):
    writing: SignalR[Writing]


class OdinHdfIO(Device):
    capture: SignalRW[Writing]
    num_captured: SignalR[int]
    num_to_capture: SignalRW[int]
    image_height: SignalRW[int]
    image_width: SignalRW[int]
    num_row_chunks: SignalRW[int]
    num_col_chunks: SignalRW[int]
    num_frames_chunks: SignalRW[int]
    file_path: SignalRW[str]
    file_name: SignalRW[str]
    data_type: SignalRW[str]
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
            self._drv.file_path.set(str(info.directory_path)),
            self._drv.file_name.set(info.filename),
            self._drv.data_type.set(
                "uint16"
            ),  # TODO: Get from eiger https://github.com/bluesky/ophyd-async/issues/529
            self._drv.num_to_capture.set(0),
        )

        await self._drv.capture.set(Writing.ON)

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self._drv.image_height.get_value(), self._drv.image_width.get_value()
        )

        return {
            "data": DataKey(
                source=self._drv.file_name.source,
                shape=list(data_shape),
                dtype="array",
                # TODO: Use correct type based on eiger https://github.com/bluesky/ophyd-async/issues/529
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self._drv.num_captured, timeout):
            yield num_captured

    async def get_indices_written(self) -> int:
        return await self._drv.num_captured.get_value()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
        # TODO: Correctly return stream https://github.com/bluesky/ophyd-async/issues/530
        raise NotImplementedError()

    async def close(self) -> None:
        await set_and_wait_for_value(self._drv.capture, Writing.OFF)
