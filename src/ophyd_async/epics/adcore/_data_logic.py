import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PureWindowsPath
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np

from ophyd_async.core import (
    DetectorDataLogic,
    PathInfo,
    PathProvider,
    SignalDataProvider,
    SignalR,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    set_and_wait_for_value,
)
from ophyd_async.epics.core import stop_busy_record

from ._io import (
    ADBaseDataType,
    ADBaseIO,
    ADFileWriteMode,
    NDArrayBaseIO,
    NDFileHDF5IO,
    NDPluginBaseIO,
    NDPluginFileIO,
)
from ._ndattribute import NDAttributeDataType, NDAttributePvDbrType


@dataclass
class PluginSignalDataLogic(DetectorDataLogic):
    driver: ADBaseIO
    signal: SignalR
    hinted: bool = True

    async def prepare_single(self, detector_name: str) -> SignalDataProvider:
        # Need to wait for all the plugins to have finished before we can read
        # the plugin signal
        await self.driver.wait_for_plugins.set(True)
        return SignalDataProvider(self.signal)

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        if self.hinted:
            return [self.signal.name]
        else:
            return []


async def get_ndarray_resource_info(
    shape_signals: Sequence[SignalR[int]],
    data_type_signal: SignalR[ADBaseDataType],
    data_key: str,
    parameters: dict[str, Any],
    frames_per_chunk: int = 1,
) -> StreamResourceInfo:
    # Grab the dimensions and datatype of the NDArray
    shape, datatype = await asyncio.gather(
        asyncio.gather(*[sig.get_value() for sig in shape_signals]),
        data_type_signal.get_value(),
    )
    if datatype is ADBaseDataType.UNDEFINED:
        raise ValueError(f"{data_type_signal.source} is blank, this is not supported")
    return StreamResourceInfo(
        data_key=data_key,
        shape=tuple(shape),
        chunk_shape=(frames_per_chunk, *shape),
        dtype_numpy=np.dtype(datatype.value.lower()).str,
        parameters=parameters,
    )


async def get_ndattribute_dtype_source(
    elements: Sequence[NDArrayBaseIO],
) -> dict[str, tuple[str, str]]:
    nd_attribute_xmls = await asyncio.gather(
        *[x.nd_attributes_file.get_value() for x in elements]
    )
    ndattribute_dtypes: dict[str, tuple[str, str]] = {}
    for maybe_xml in nd_attribute_xmls:
        # This is the check that ADCore does to see if it is an XML string
        # rather than a filename to parse
        if "<Attributes>" in maybe_xml:
            root = ET.fromstring(maybe_xml)
            for child in root:
                if child.attrib.get("type", "EPICS_PV") == "EPICS_PV":
                    dbrtype = child.attrib.get("dbrtype", "DBR_NATIVE")
                    if dbrtype == "DBR_NATIVE":
                        raise RuntimeError(
                            f"NDAttribute {child.attrib['name']} has dbrtype "
                            "DBR_NATIVE, which is not supported"
                        )
                    dtype_numpy = NDAttributePvDbrType[dbrtype].value
                    source = "ca://" + child.attrib["source"]
                else:
                    datatype = child.attrib.get("datatype", "INT")
                    dtype_numpy = NDAttributeDataType[datatype].value
                    source = ""
                ndattribute_dtypes[child.attrib["name"]] = (dtype_numpy, source)
    return ndattribute_dtypes


async def prepare_file_paths(
    path_info: PathInfo, file_template: str, writer: NDPluginFileIO
):
    # Set the directory creation depth first, since dir creation callback happens
    # when directory path PV is processed.
    await writer.create_directory.set(path_info.create_dir_depth)
    # When setting the path for windows based AD IOCs, areaDetector adds a '/'
    # rather than a '\\', which will cause the readback to never register the
    # same value.
    # Ensure that trailing separator is added to the directory path to avoid this.
    if isinstance(path_info.directory_path, PureWindowsPath):
        directory_path = f"{path_info.directory_path}\\"
    else:
        directory_path = f"{path_info.directory_path}/"
    await asyncio.gather(
        writer.file_path.set(directory_path),
        writer.file_name.set(path_info.filename),
        writer.file_template.set(file_template),
        writer.auto_increment.set(True),
        writer.file_number.set(0),
        writer.file_write_mode.set(ADFileWriteMode.STREAM),
    )
    # Check the path exists on the host
    if not await writer.file_path_exists.get_value():
        msg = f"Path {directory_path} doesn't exist or not writable!"
        raise FileNotFoundError(msg)
    # Overwrite num_capture to go forever
    await writer.num_capture.set(0)


@dataclass
class ADHDFDataLogic(DetectorDataLogic):
    """Data logic for AreaDetector HDF5 writer plugin.

    :param shape_signals: Signals that provide the shape of the NDArray.
    :param data_type_signal: Signal that provides the data type of the NDArray.
    :param path_provider: Callable that provides path information for file writing.
    :param driver: The AreaDetector driver instance.
    :param writer: The NDFileHDFIO plugin instance.
    :param plugins: Additional NDPluginBaseIO instances to extract NDAttributes from.
    :param datakey_suffix: Suffix to append to the data key for the main dataset
    """

    shape_signals: Sequence[SignalR[int]]
    data_type_signal: SignalR[ADBaseDataType]
    path_provider: PathProvider
    driver: ADBaseIO
    writer: NDFileHDF5IO
    plugins: Sequence[NDPluginBaseIO] = ()
    datakey_suffix: str = ""

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(self.writer.name)
        # Determine number of frames that will be saved per HDF chunk.
        # On a fresh IOC startup, this is set to zero until the first capture,
        # so if it is zero, set it to 1.
        frames_per_chunk = await self.writer.num_frames_chunks.get_value()
        if frames_per_chunk == 0:
            frames_per_chunk = 1
            await self.writer.num_frames_chunks.set(frames_per_chunk)
        # Setup the HDF writer
        await asyncio.gather(
            self.writer.chunk_size_auto.set(True),
            self.writer.num_extra_dims.set(0),
            self.writer.lazy_open.set(True),
            self.writer.swmr_mode.set(True),
            self.writer.xml_file_name.set(""),
            prepare_file_paths(
                path_info=path_info, file_template="%s%s.h5", writer=self.writer
            ),
        )
        # Start capturing
        await set_and_wait_for_value(
            self.writer.capture, True, wait_for_set_completion=False
        )
        # Return a provider that reflects what we have made
        main_dataset = await get_ndarray_resource_info(
            shape_signals=self.shape_signals,
            data_type_signal=self.data_type_signal,
            data_key=detector_name + self.datakey_suffix,
            parameters={"dataset": "/entry/data/data"},
            frames_per_chunk=frames_per_chunk,
        )
        ndattribute_dtype_sources = await get_ndattribute_dtype_source(
            (self.driver, *self.plugins)
        )
        ndattribute_datasets = [
            StreamResourceInfo(
                data_key=name,
                shape=(),
                # NDAttributes appear to always be configured with
                # this chunk size
                chunk_shape=(16384,),
                dtype_numpy=dtype_numpy,
                source=source,
                parameters={"dataset": f"/entry/instrument/NDAttributes/{name}"},
            )
            for name, (dtype_numpy, source) in ndattribute_dtype_sources.items()
        ]
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{path_info.filename}.h5",
            resources=[main_dataset] + ndattribute_datasets,
            mimetype="application/x-hdf5",
            collections_written_signal=self.writer.num_captured,
            flush_signal=self.writer.flush_now,
        )

    async def stop(self) -> None:
        await stop_busy_record(self.writer.capture)

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        # The main NDArray dataset is always hinted
        return [detector_name + self.datakey_suffix]


@dataclass
class ADMultipartDataLogic(DetectorDataLogic):
    """Data logic for multipart AreaDetector file writers (e.g. JPEG, TIFF).

    :param shape_signals: Signals that provide the shape of the NDArray.
    :param data_type_signal: Signal that provides the data type of the NDArray.
    :param path_provider: Callable that provides path information for file writing.
    :param writer: The NDFilePluginIO instance.
    :param extension: File extension for the written files (e.g. ".jpg", ".tiff").
    :param mimetype:
        Mimetype for the written files (e.g. "multipart/related;type=image/jpeg").
    :param datakey_suffix: Suffix to append to the data key for the main dataset
    """

    shape_signals: Sequence[SignalR[int]]
    data_type_signal: SignalR[ADBaseDataType]
    path_provider: PathProvider
    writer: NDPluginFileIO
    extension: str
    mimetype: str
    datakey_suffix: str = ""

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(self.writer.name)
        # Setup the file writer
        await prepare_file_paths(
            path_info=path_info,
            file_template="%s%s_%6.6d" + self.extension,
            writer=self.writer,
        )
        # Start capturing
        await set_and_wait_for_value(
            self.writer.capture, True, wait_for_set_completion=False
        )
        # Return a provider that reflects what we have made
        main_dataset = await get_ndarray_resource_info(
            shape_signals=self.shape_signals,
            data_type_signal=self.data_type_signal,
            data_key=detector_name + self.datakey_suffix,
            parameters={
                "file_template": path_info.filename + "_{:06d}" + self.extension
            },
        )
        return StreamResourceDataProvider(
            uri=path_info.directory_uri,  # type: ignore
            resources=[main_dataset],
            mimetype=self.mimetype,
            collections_written_signal=self.writer.num_captured,
        )

    async def stop(self) -> None:
        await stop_busy_record(self.writer.capture)

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        # The main NDArray dataset is always hinted
        return [detector_name + self.datakey_suffix]


class ADWriterType(Enum):
    HDF = "HDF"
    JPEG = "JPEG"
    TIFF = "TIFF"


def make_writer_data_logic(
    prefix: str,
    path_provider: PathProvider,
    writer_suffix: str | None,
    driver: ADBaseIO,
    writer_type: ADWriterType,
    plugins: Mapping[str, NDPluginBaseIO] | None = None,
) -> tuple[NDPluginFileIO, DetectorDataLogic]:
    plugins = plugins or {}
    shape_signals = [driver.array_size_y, driver.array_size_x]
    data_type_signal = driver.data_type
    match writer_type:
        case ADWriterType.HDF:
            writer = NDFileHDF5IO(f"{prefix}{writer_suffix or 'HDF1:'}")
            data_logic = ADHDFDataLogic(
                shape_signals=shape_signals,
                data_type_signal=data_type_signal,
                path_provider=path_provider,
                driver=driver,
                writer=writer,
                plugins=list(plugins.values()),
            )
        case ADWriterType.JPEG:
            writer = NDPluginFileIO(f"{prefix}{writer_suffix or 'JPEG1:'}")
            data_logic = ADMultipartDataLogic(
                shape_signals=shape_signals,
                data_type_signal=data_type_signal,
                path_provider=path_provider,
                writer=writer,
                extension=".jpg",
                mimetype="multipart/related;type=image/jpeg",
            )
        case ADWriterType.TIFF:
            writer = NDPluginFileIO(f"{prefix}{writer_suffix or 'TIFF1:'}")
            data_logic = ADMultipartDataLogic(
                shape_signals=shape_signals,
                data_type_signal=data_type_signal,
                path_provider=path_provider,
                writer=writer,
                extension=".tiff",
                mimetype="multipart/related;type=image/tiff",
            )
        case _:
            raise RuntimeError("Not implemented")
    return writer, data_logic
