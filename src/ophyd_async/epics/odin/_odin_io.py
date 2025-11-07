import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import (  # type: ignore
    DataKey,  # type: ignore
)


from ophyd_async.core._log import logger
from xml.etree import ElementTree as ET

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
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
    HDFDatasetDescription,
    HDFDocumentComposer,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    stop_busy_record,
)

from ophyd_async.epics.adcore import NDPluginBaseIO
from ophyd_async.epics.adcore._utils import (
    convert_param_dtype_to_np,
    convert_pv_dtype_to_np,
)

class Writing(StrictEnum):
    CAPTURE = "Capture"
    DONE = "Done"

from dodal.log import LOGGER


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
        self.id = epics_signal_r(str, f"{prefix}AcquisitionID_RBV")

        self.num_frames_chunks = epics_signal_rw(int, prefix + "NumFramesChunks")
        self.meta_active = epics_signal_r(str, prefix + "META:AcquisitionActive_RBV")
        self.meta_writing = epics_signal_r(str, prefix + "META:Writing_RBV")
        self.meta_file_name = epics_signal_r(str, f"{prefix}META:FileName_RBV")
        self.meta_stop = epics_signal_rw(bool, f"{prefix}META:Stop")

        self.fan_ready = epics_signal_rw(float, f"{prefix}FAN:StateReady_RBV")

        self.data_type = epics_signal_rw_rbv(str, f"{prefix}DataType")

        super().__init__(name)


class OdinWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: PathProvider,
        odin_driver: Odin,
        detector_bit_depth: SignalR[int],
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        self._drv = odin_driver
        self._path_provider = path_provider
        self._detector_bit_depth = Reference(detector_bit_depth)
        self._plugins = plugins
        self._capture_status: AsyncStatus | None = None
        self._datasets: list[HDFDatasetDescription] = []
        self._composer: HDFDocumentComposer | None = None

        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        self._composer = None

        info = self._path_provider(device_name=name)
        self._exposures_per_event = exposures_per_event
        self.data_shape = await self.get_data_shape()


        self._path_info = self._path_provider(device_name=name)

        await asyncio.gather(
            self._drv.data_type.set(
                f"UInt{await self._detector_bit_depth().get_value()}"
            ),
            self._drv.num_to_capture.set(0),
            self._drv.file_path.set(str(info.directory_path)),
            self._drv.file_name.set(info.filename),
        )

        await asyncio.gather(
            wait_for_value(
                self._drv.meta_file_name, info.filename, timeout=DEFAULT_TIMEOUT
            ),
            wait_for_value(self._drv.id, info.filename, timeout=DEFAULT_TIMEOUT),
            wait_for_value(self._drv.meta_active, "Active", timeout=DEFAULT_TIMEOUT),
        )

        self._capture_status = await set_and_wait_for_value(
            self._drv.capture, Writing.CAPTURE, wait_for_set_completion=False
        )

        await asyncio.gather(
            wait_for_value(self._drv.capture_rbv, "Capturing", timeout=DEFAULT_TIMEOUT),
            wait_for_value(self._drv.meta_writing, "Writing", timeout=DEFAULT_TIMEOUT),
        )

        # Add the main data
        self._datasets = [
            HDFDatasetDescription(
                data_key=name,
                dataset=f"/entry/data",
                shape=(self._exposures_per_event, *self.data_shape),
                dtype_numpy="<u2",
                chunk_shape=(self._exposures_per_event, *self.data_shape),
            )
        ]

        await self.append_plugins_to_datasets()

        self._composer = HDFDocumentComposer(
            f"{info.directory_uri}{info.filename}.h5",
            self._datasets,
        )

        description = await self._describe(name)

        return description

    async def get_data_shape(self) -> tuple[int, int]:
        data_shape = await asyncio.gather(
            self._drv.image_height.get_value(), self._drv.image_width.get_value()
        )

        return data_shape
    

    async def _describe(self, name: str) -> dict[str, DataKey]:
      
        describe = {
            ds.data_key: DataKey(
                source=self._drv.file_name.source,
                shape=list(ds.shape),
                dtype="array" if self._exposures_per_event > 1 or len(ds.shape) > 1
                else "number",
                # TODO: Use correct type based on eiger https://github.com/bluesky/ophyd-async/issues/529
                dtype_numpy="<u2",
                external="STREAM:",
            )
            for ds in self._datasets
        }

        return describe


    async def append_plugins_to_datasets(self) -> None:

        if self._plugins is not None:

            # And all the scalar datasets
            for plugin in self._plugins.values():
                maybe_xml = await plugin.nd_attributes_file.get_value()
                # This is the check that ADCore does to see if it is an XML string
                # rather than a filename to parse
                if "<Attributes>" in maybe_xml:
                    root = ET.fromstring(maybe_xml)
                    for child in root:
                        data_key = child.attrib["name"]
                        if child.attrib.get("type", "EPICS_PV") == "EPICS_PV":
                            np_datatype = convert_pv_dtype_to_np(
                                child.attrib.get("dbrtype", "DBR_NATIVE")
                            )
                        else:
                            np_datatype = convert_param_dtype_to_np(
                                child.attrib.get("datatype", "INT")
                            )
                        self._datasets.append(
                            HDFDatasetDescription(
                                data_key=data_key,
                                dataset=f"/entry/instrument/NDAttributes/{data_key}",
                                shape=(self._exposures_per_event,)
                                if self._exposures_per_event > 1
                                else (),
                                dtype_numpy=np_datatype,
                                # NDAttributes appear to always be configured with
                                # this chunk size
                                chunk_shape=(16384,),
                            )
                        )
        return
    
    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self._drv.num_captured, timeout):
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        return await self._drv.num_captured.get_value() // self._exposures_per_event

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if self._composer is None:
            msg = f"open() not called on {self}"
            raise RuntimeError(msg)
        for doc in self._composer.make_stream_docs(indices_written):
            yield doc

    async def close(self) -> None:
        await stop_busy_record(self._drv.capture, Writing.DONE, timeout=DEFAULT_TIMEOUT)
        await self._drv.meta_stop.set(True, wait=True)
        if self._capture_status and not self._capture_status.done:
            await self._capture_status
        self._capture_status = None
