import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey  # type: ignore

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    DeviceVector,
    PathProvider,
    Reference,
    SignalR,
    StrictEnum,
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)


class Writing(StrictEnum):
    CAPTURE = "Capture"
    DONE = "Done"


class OdinNode(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.writing = epics_signal_r(str, f"{prefix}Writing_RBV")
        self.frames_dropped = epics_signal_r(int, f"{prefix}FramesDropped_RBV")
        self.frames_time_out = epics_signal_r(int, f"{prefix}FramesTimedOut_RBV")
        self.error_status = epics_signal_r(str, f"{prefix}FPErrorState_RBV")
        self.fp_initialised = epics_signal_r(int, f"{prefix}FPProcessConnected_RBV")
        self.fr_initialised = epics_signal_r(int, f"{prefix}FRProcessConnected_RBV")
        self.num_captured = epics_signal_r(int, f"{prefix}NumCaptured_RBV")
        self.clear_errors = epics_signal_rw(int, f"{prefix}FPClearErrors")
        self.error_message = epics_signal_rw(str, f"{prefix}FPErrorMessage_RBV")

        super().__init__(name)


class Odin(Device):
    def __init__(self, prefix: str, name: str = "", nodes: int = 4) -> None:
        # default nodes is set to 4, MX 16M Eiger detectors - nodes = 4.
        # B21 4M Eiger detector - nodes = 1
        self.nodes = DeviceVector(
            {i: OdinNode(f"{prefix[:-1]}{i + 1}:") for i in range(nodes)}
        )

        self.capture = epics_signal_rw(Writing, f"{prefix}Capture")
        self.capture_rbv = epics_signal_r(str, prefix + "Capture_RBV")
        self.num_captured = epics_signal_r(int, f"{prefix}NumCaptured_RBV")
        self.num_to_capture = epics_signal_rw_rbv(int, f"{prefix}NumCapture")

        self.start_timeout = epics_signal_rw(str, f"{prefix}StartTimeout")
        self.timeout_active_rbv = epics_signal_r(str, f"{prefix}TimeoutActive_RBV")

        self.image_height = epics_signal_rw_rbv(int, f"{prefix}ImageHeight")
        self.image_width = epics_signal_rw_rbv(int, f"{prefix}ImageWidth")

        self.num_row_chunks = epics_signal_rw_rbv(int, f"{prefix}NumRowChunks")
        self.num_col_chunks = epics_signal_rw_rbv(int, f"{prefix}NumColChunks")

        self.file_path = epics_signal_rw_rbv(str, f"{prefix}FilePath")
        self.file_name = epics_signal_rw_rbv(str, f"{prefix}FileName")

        self.num_frames_chunks = epics_signal_rw(int, prefix + "NumFramesChunks")
        self.meta_active = epics_signal_r(str, prefix + "META:AcquisitionActive_RBV")
        self.meta_writing = epics_signal_r(str, prefix + "META:Writing_RBV")

        self.data_type = epics_signal_rw_rbv(str, f"{prefix}DataType")

        super().__init__(name)


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        odin_driver: Odin,
        eiger_bit_depth: SignalR[int],
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        self._eiger_bit_depth = Reference(eiger_bit_depth)
        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        info = self._path_provider(device_name=name)
        self._exposures_per_event = exposures_per_event

        await asyncio.gather(
            self._drv.file_path.set(str(info.directory_path)),
            self._drv.file_name.set(info.filename),
            self._drv.data_type.set(f"UInt{await self._eiger_bit_depth().get_value()}"),
            self._drv.num_to_capture.set(0),
        )

        await wait_for_value(self._drv.meta_active, "Active", timeout=DEFAULT_TIMEOUT)

        await self._drv.capture.set(
            Writing.CAPTURE, wait=False
        )  # TODO: Investigate why we do not get a put callback when setting capture pv https://github.com/bluesky/ophyd-async/issues/866

        await asyncio.gather(
            wait_for_value(self._drv.capture_rbv, "Capturing", timeout=DEFAULT_TIMEOUT),
            wait_for_value(self._drv.meta_writing, "Writing", timeout=DEFAULT_TIMEOUT),
        )

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        data_shape = await asyncio.gather(
            self._drv.image_height.get_value(), self._drv.image_width.get_value()
        )

        return {
            "data": DataKey(
                source=self._drv.file_name.source,
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
        async for num_captured in observe_value(self._drv.num_captured, timeout):
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        return await self._drv.num_captured.get_value() // self._exposures_per_event

    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: Correctly return stream https://github.com/bluesky/ophyd-async/issues/530
        raise NotImplementedError()

    async def close(self) -> None:
        await set_and_wait_for_value(self._drv.capture, Writing.DONE)
