import asyncio
from enum import Enum
from typing import AsyncGenerator, AsyncIterator, Dict

from bluesky.protocols import DataKey, StreamAsset

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    DeviceVector,
    NameProvider,
    PathProvider,
    observe_value,
)
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw_rbv,
    epics_signal_w,
)


class Writing(str, Enum):
    ON = "ON"
    OFF = "OFF"


class OdinNode(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.writing = epics_signal_r(Writing, f"{prefix}HDF:Writing")

        # Cannot find:
        # FPClearErrors
        # FPErrorState_RBV
        # FPErrorMessage_RBV

        self.connected = epics_signal_r(
            bool, f"{prefix}Connected"
        )  # Assuming this is both FPProcessConnected_RBV and FRProcessConnected_RBV

        # Usually assert that FramesTimedOut_RBV and FramesDropped_RBV are 0
        # , do these exist or do we want to assert something else?

        super().__init__(name)


class Odin(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nodes = DeviceVector({i: OdinNode(f"{prefix}FP{i}:") for i in range(4)})

        self.capture = epics_signal_w(Writing, f"{prefix}ConfigHdfWrite")
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
        name_provider: NameProvider,
        odin_driver: Odin,
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        self._name_provider = name_provider
        super().__init__()

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        info = self._path_provider(device_name=self._name_provider())

        await asyncio.gather(
            self._drv.file_path.set(str(info.directory_path)),
            self._drv.file_name.set(info.filename),
            self._drv.data_type.set("uint16"),  # TODO: get from eiger
            self._drv.num_to_capture.set(1),
        )

        # await wait_for_value(self._drv.acquisition_id, info.filename, DEFAULT_TIMEOUT)

        await self._drv.capture.set(Writing.ON)

        return await self._describe()

    async def _describe(self) -> Dict[str, DataKey]:
        """
        Return a describe based on the datasets PV
        """
        # TODO: fill this in properly
        return {
            "data": DataKey(
                source="",
                shape=[],
                dtype="number",
                dtype_numpy="<f8",
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
        # TODO
        pass

    async def close(self) -> None:
        await self._drv.capture.set(Writing.OFF)
