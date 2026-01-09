import asyncio
from collections.abc import Sequence
from enum import Enum
from pathlib import PureWindowsPath
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
from bluesky.protocols import Hints

from ophyd_async.core import (
    DetectorArmLogic,
    DetectorDataLogic,
    DetectorTriggerLogic,
    PathInfo,
    PathProvider,
    SignalR,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    set_and_wait_for_value,
)
from ophyd_async.epics.core import stop_busy_record

from ._detector import AreaDetector
from ._io import (
    ADBaseDataType,
    ADBaseIO,
    ADFileWriteMode,
    NDArrayBaseIO,
    NDFileHDFIO,
    NDFilePluginIO,
    NDPluginBaseIO,
)
from ._ndattribute import NDAttributeDataType, NDAttributePvDbrType


async def get_ndarray_resource_info(
    driver: ADBaseIO,
    data_key: str,
    parameters: dict[str, Any],
    frames_per_chunk: int = 1,
) -> StreamResourceInfo:
    # Create the chain of driver and plugins and get driver params
    size_x, size_y, datatype = await asyncio.gather(
        driver.array_size_x.get_value(),
        driver.array_size_y.get_value(),
        driver.data_type.get_value(),
    )
    if datatype is ADBaseDataType.UNDEFINED:
        raise ValueError(f"{driver.data_type.source} is blank, this is not supported")
    shape = (size_y, size_x)
    return StreamResourceInfo(
        data_key=data_key,
        shape=shape,
        dtype_numpy=np.dtype(datatype.value.lower()).str,
        chunk_shape=(frames_per_chunk, *shape),
        parameters=parameters,
    )


async def get_ndattribute_dtypes(elements: Sequence[NDArrayBaseIO]) -> dict[str, str]:
    nd_attribute_xmls = await asyncio.gather(
        *[x.nd_attributes_file.get_value() for x in elements]
    )
    ndattribute_dtypes: dict[str, str] = {}
    for maybe_xml in nd_attribute_xmls:
        # This is the check that ADCore does to see if it is an XML string
        # rather than a filename to parse
        if "<Attributes>" in maybe_xml:
            root = ET.fromstring(maybe_xml)
            for child in root:
                if child.attrib.get("type", "EPICS_PV") == "EPICS_PV":
                    dbrtype = child.attrib.get("dbrtype", "DBR_NATIVE")
                    dtype_numpy = NDAttributePvDbrType(dbrtype).value
                else:
                    datatype = child.attrib.get("datatype", "INT")
                    dtype_numpy = NDAttributeDataType(datatype).value
                ndattribute_dtypes[child.attrib["name"]] = dtype_numpy
    return ndattribute_dtypes


async def prepare_file_paths(
    path_info: PathInfo, file_template: str, writer: NDFilePluginIO
):
    # Set the directory creation depth first, since dir creation callback happens
    # when directory path PV is processed.
    await writer.create_directory.set(path_info.create_dir_depth)
    # Need to ensure that trailing separator is added to the directory path.
    # When setting the path for windows based AD IOCs, a '/' is added rather than
    # a '\\', which will cause the readback to never register the same value.
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


class ADHDFDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        driver: ADBaseIO,
        writer: NDFileHDFIO,
        plugins: Sequence[NDPluginBaseIO],
    ):
        self.path_provider = path_provider
        self.driver = driver
        self.writer = writer
        self.plugins = plugins

    async def prepare_unbounded(self, device_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(device_name)
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
            driver=self.driver,
            data_key=device_name,
            parameters={"dataset": "/entry/data/data"},
            frames_per_chunk=frames_per_chunk,
        )
        ndattribute_dtypes = await get_ndattribute_dtypes((self.driver, *self.plugins))
        ndattribute_datasets = [
            StreamResourceInfo(
                data_key=name,
                shape=(),
                dtype_numpy=dtype_numpy,
                # NDAttributes appear to always be configured with
                # this chunk size
                chunk_shape=(16384,),
                parameters={"dataset": f"/entry/instrument/NDAttributes/{name}"},
            )
            for name, dtype_numpy in ndattribute_dtypes.items()
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

    def get_hints(self, device_name: str) -> Hints:
        # The main NDArray dataset is always hinted
        return {"fields": [device_name]}


class ADMultipartDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        driver: ADBaseIO,
        writer: NDFilePluginIO,
        extension: str,
        mimetype: str,
    ):
        self.path_provider = path_provider
        self.driver = driver
        self.writer = writer
        self.extension = extension
        self.mimetype = mimetype

    async def prepare_unbounded(self, device_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(device_name)
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
            driver=self.driver,
            data_key=device_name,
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

    def get_hints(self, device_name: str) -> Hints:
        # The main NDArray dataset is always hinted
        return {"fields": [device_name]}


class ADWriterType(Enum):
    HDF = "HDF"
    JPEG = "JPEG"
    TIFF = "TIFF"

    def make_detector(
        self,
        prefix: str,
        path_provider: PathProvider,
        writer_suffix: str | None,
        driver: ADBaseIO,
        trigger_logic: DetectorTriggerLogic,
        arm_logic: DetectorArmLogic,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> AreaDetector:
        plugins = plugins or {}
        match self:
            case ADWriterType.HDF:
                writer = NDFileHDFIO(f"{prefix}{writer_suffix or 'HDF1:'}")
                data_logic = ADHDFDataLogic(
                    driver=driver,
                    writer=writer,
                    plugins=list(plugins.values()),
                    path_provider=path_provider,
                )
            case ADWriterType.JPEG:
                writer = NDFilePluginIO(f"{prefix}{writer_suffix or 'JPEG1:'}")
                data_logic = ADMultipartDataLogic(
                    driver=driver,
                    writer=writer,
                    path_provider=path_provider,
                    extension=".jpg",
                    mimetype="multipart/related;type=image/jpeg",
                )
            case ADWriterType.TIFF:
                writer = NDFilePluginIO(f"{prefix}{writer_suffix or 'TIFF1:'}")
                data_logic = ADMultipartDataLogic(
                    driver=driver,
                    writer=writer,
                    path_provider=path_provider,
                    extension=".tiff",
                    mimetype="multipart/related;type=image/tiff",
                )
            case _:
                raise RuntimeError("Not implemented")
        return AreaDetector(
            driver=driver,
            trigger_logic=trigger_logic,
            data_logic=data_logic,
            arm_logic=arm_logic,
            plugins=dict(writer=writer, **plugins),
            config_sigs=config_sigs,
            name=name,
        )
