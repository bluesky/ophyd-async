import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DetectorWriter,
    Device,
    DeviceVector,
    PathProvider,
    StrictEnum,
    observe_value,
    set_and_wait_for_value,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)


class Writing(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class OdinNode(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.writing = epics_signal_r(Writing, f"{prefix}HDF:Writing")
        self.connected = epics_signal_r(bool, f"{prefix}Connected")

        super().__init__(name)


class Odin(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nodes = DeviceVector({i: OdinNode(f"{prefix}FP{i}:") for i in range(4)})

        self.capture = epics_signal_rw(
            Writing, f"{prefix}Writing", f"{prefix}ConfigHdfWrite"
        )
        self.num_captured = epics_signal_r(int, f"{prefix}FramesWritten")
        self.num_to_capture = epics_signal_rw_rbv(int, f"{prefix}ConfigHdfFrames")

        self.start_timeout = epics_signal_rw_rbv(int, f"{prefix}TimeoutTimerPeriod")

        self.image_height = epics_signal_rw_rbv(int, f"{prefix}DatasetDataDims0")
        self.image_width = epics_signal_rw_rbv(int, f"{prefix}DatasetDataDims1")

        self.num_row_chunks = epics_signal_rw_rbv(int, f"{prefix}DatasetDataChunks1")
        self.num_col_chunks = epics_signal_rw_rbv(int, f"{prefix}DatasetDataChunks2")

        self.file_path = epics_signal_rw_rbv(str, f"{prefix}ConfigHdfFilePath")
        self.file_name = epics_signal_rw_rbv(str, f"{prefix}ConfigHdfFilePrefix")

        self.acquisition_id = epics_signal_rw_rbv(
            str, f"{prefix}ConfigHdfAcquisitionId"
        )

        self.data_type = epics_signal_rw_rbv(str, f"{prefix}DatasetDataDatatype")

        super().__init__(name)


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        odin_driver: Odin,
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        super().__init__()

    async def open(self, name: str, multiplier: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=name)

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
        self, timeout: float
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
