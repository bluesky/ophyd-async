import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, Generic
from xml.etree import ElementTree as ET

import numpy as np

from ophyd_async.core import (
    DetectorDataLogic,
    EnableDisable,
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
    ADBaseColorMode,
    ADBaseDataType,
    ADBaseIO,
    ADFileWriteMode,
    NDArrayBaseIO,
    NDFileHDF5IO,
    NDPluginBaseIO,
    NDPluginFileIO,
    NDPluginFileIOT,
)
from ._ndattribute import NDAttributeDataType, NDAttributePvDbrType


@dataclass
class PluginSignalDataLogic(DetectorDataLogic):
    driver: ADBaseIO
    signal: SignalR
    hinted: bool = True

    async def prepare_single(self, datakey_name: str) -> SignalDataProvider:
        # Need to wait for all the plugins to have finished before we can read
        # the plugin signal
        await self.driver.wait_for_plugins.set(True)
        return SignalDataProvider(self.signal)

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return [self.signal.name] if self.hinted else []


@dataclass
class NDArrayDescription:
    """Signals that describe the shape and data type of an NDArray frame.

    :param shape_signals: Signals providing the frame dimensions (e.g.
        ``size_y``, ``size_x``).  Zero-valued entries are filtered out, so it
        is safe to include ``array_size_z`` for 2-D detectors.
    :param data_type_signal: Signal providing the pixel data type.
    :param color_mode_signal: Signal providing the colour mode (MONO or RGB1).
    """

    shape_signals: Sequence[SignalR[int]]
    data_type_signal: SignalR[ADBaseDataType]
    color_mode_signal: SignalR[ADBaseColorMode]


async def get_ndarray_resource_info(
    array_description: NDArrayDescription,
    data_key: str,
    parameters: dict[str, Any],
    frames_per_chunk: int = 1,
) -> StreamResourceInfo:
    # Grab the dimensions and datatype of the NDArray
    shape, datatype, color_mode = await asyncio.gather(
        asyncio.gather(*[sig.get_value() for sig in array_description.shape_signals]),
        array_description.data_type_signal.get_value(),
        array_description.color_mode_signal.get_value(),
    )
    # Remove entries in shape that are zero
    shape = [x for x in shape if x > 0]
    if datatype is ADBaseDataType.UNDEFINED:
        raise ValueError(
            f"{array_description.data_type_signal.source} is blank, "
            "this is not supported"
        )
    if color_mode == ADBaseColorMode.RGB1:
        shape = [3, *shape]
    elif color_mode != ADBaseColorMode.MONO:
        raise RuntimeError(
            f"Unsupported ColorMode {color_mode}! Only Mono and RGB1 are supported."
        )
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

    :param array_description: Signals describing the NDArray shape and data type.
    :param path_provider: Callable that provides path information for file writing.
    :param driver: The AreaDetector driver instance.
    :param writer: The NDFileHDFIO plugin instance.
    :param plugins: Additional NDPluginBaseIO instances to extract NDAttributes from.
    :param datakey_suffix: Suffix to append to the data key for the main dataset
    """

    array_description: NDArrayDescription
    path_provider: PathProvider
    driver: ADBaseIO
    writer: NDFileHDF5IO
    plugins: Sequence[NDPluginBaseIO] = ()
    datakey_suffix: str = ""

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(datakey_name)
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
            self.writer.enable_callbacks.set(EnableDisable.ENABLE),
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
            array_description=self.array_description,
            data_key=datakey_name,
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

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        # The main NDArray dataset is always hinted
        return [datakey_name]


@dataclass
class ADMultipartDataLogic(DetectorDataLogic):
    """Data logic for multipart AreaDetector file writers (e.g. JPEG, TIFF).

    :param array_description: Signals describing the NDArray shape and data type.
    :param path_provider: Callable that provides path information for file writing.
    :param writer: The NDFilePluginIO instance.
    :param extension: File extension for the written files (e.g. ".jpg", ".tiff").
    :param mimetype:
        Mimetype for the written files (e.g. "multipart/related;type=image/jpeg").
    :param datakey_suffix: Suffix to append to the data key for the main dataset
    """

    array_description: NDArrayDescription
    path_provider: PathProvider
    writer: NDPluginFileIO
    extension: str
    mimetype: str
    datakey_suffix: str = ""

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(datakey_name)
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
            array_description=self.array_description,
            data_key=datakey_name,
            parameters={"template": path_info.filename + "_{:06d}" + self.extension},
        )
        return StreamResourceDataProvider(
            # TODO: remove the type ignore after
            # https://github.com/bluesky/ophyd-async/issues/1186
            uri=path_info.directory_uri,
            resources=[main_dataset],
            mimetype=self.mimetype,
            collections_written_signal=self.writer.num_captured,
        )

    async def stop(self) -> None:
        await stop_busy_record(self.writer.capture)

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        # The main NDArray dataset is always hinted
        return [datakey_name]


@dataclass
class ADWriterFactory(Generic[NDPluginFileIOT]):
    """Factory that creates a file-writer plugin and its matching data logic.

    Construct using the classmethods `hdf`, `jpeg`, or `tiff`, then pass one
    or more instances to `AreaDetector` as positional `*writer_factories`
    arguments.  When the detector is initialised `__call__` is invoked with
    the detector's PV `prefix`, its `driver`, and the flat list of extra
    `plugins`; it returns the writer device and the corresponding
    `DetectorDataLogic`.

    :param writer_cls: Concrete `NDPluginFileIO` subclass to instantiate.
    :param writer_suffix: PV suffix appended to *prefix* to form the writer's PV prefix.
    :param writer_name:
        Attribute name under which the writer device is stored on the
        `AreaDetector` instance.  Each static method defaults to its own name
        (``"hdf"``, ``"jpeg"``, ``"tiff"``); override when passing multiple
        factories so each writer gets a distinct name.
    :param datakey_suffix: Suffix appended to the datakey name in stream resources.
    :param array_description:
        Override the array shape/type description built from the driver.
        May be an `NDArrayDescription` instance or a callable
        ``(driver) → NDArrayDescription``; use a callable when the description
        depends on signals that are only available once the driver has been
        constructed (e.g. inside a detector subclass that creates its own driver).
    :param data_logic_factory:
        Callable ``(writer, array_description, driver, plugins) → DetectorDataLogic``
        that builds the data logic given the already-constructed writer.
    """

    writer_cls: type[NDPluginFileIOT]
    writer_suffix: str
    writer_name: str
    datakey_suffix: str
    array_description: (
        NDArrayDescription | Callable[[ADBaseIO], NDArrayDescription] | None
    )
    data_logic_factory: Callable[
        [NDPluginFileIOT, NDArrayDescription, ADBaseIO, Sequence[NDPluginBaseIO]],
        DetectorDataLogic,
    ]

    def __call__(
        self,
        prefix: str,
        driver: ADBaseIO,
        plugins: Sequence[NDPluginBaseIO],
    ) -> tuple[NDPluginFileIOT, DetectorDataLogic]:
        """Instantiate the writer plugin and build the data logic.

        :param prefix: EPICS PV prefix for the detector (same as `AreaDetector.prefix`).
        :param driver: The detector driver, used to read array shape/type metadata.
        :param plugins: Additional plugins whose NDAttribute XML files should be
            included in HDF5 metadata.
        :return: ``(writer, data_logic)`` tuple ready to attach to the detector.
        """
        writer = self.writer_cls(prefix + self.writer_suffix)
        if callable(self.array_description):
            array_description = self.array_description(driver)
        elif self.array_description is not None:
            array_description = self.array_description
        else:
            array_description = NDArrayDescription(
                shape_signals=[
                    driver.array_size_z,
                    driver.array_size_y,
                    driver.array_size_x,
                ],
                data_type_signal=driver.data_type,
                color_mode_signal=driver.color_mode,
            )
        data_logic = self.data_logic_factory(writer, array_description, driver, plugins)
        return writer, data_logic

    @staticmethod
    def hdf(
        path_provider: PathProvider,
        writer_suffix: str = "HDF1:",
        writer_name: str = "hdf",
        datakey_suffix: str = "",
        array_description: NDArrayDescription
        | Callable[[ADBaseIO], NDArrayDescription]
        | None = None,
    ) -> "ADWriterFactory[NDFileHDF5IO]":
        """Create a factory for an HDF5 file writer.

        :param path_provider: Provides file path information for each acquisition.
        :param writer_suffix: PV suffix for the NDFileHDF5 plugin, defaults to
            ``HDF1:``.
        :param writer_name:
            Attribute name for the writer on the detector, defaults to
            ``"hdf"``.
        :param datakey_suffix: Suffix appended to the datakey name, defaults to ``""``.
        :param array_description:
            Override the array shape/type description built from the driver.
            Pass an `NDArrayDescription` or a callable ``(driver) → NDArrayDescription``
            when the shape/type comes from a plugin rather than the main driver
            (e.g. an ROI plugin).
        """
        return ADWriterFactory(
            writer_cls=NDFileHDF5IO,
            writer_suffix=writer_suffix,
            writer_name=writer_name,
            datakey_suffix=datakey_suffix,
            array_description=array_description,
            data_logic_factory=lambda writer, desc, driver, plugins: ADHDFDataLogic(
                array_description=desc,
                path_provider=path_provider,
                driver=driver,
                writer=writer,
                plugins=list(plugins),
                datakey_suffix=datakey_suffix,
            ),
        )

    @staticmethod
    def jpeg(
        path_provider: PathProvider,
        writer_suffix: str = "JPEG1:",
        writer_name: str = "jpeg",
        datakey_suffix: str = "",
        array_description: NDArrayDescription
        | Callable[[ADBaseIO], NDArrayDescription]
        | None = None,
    ) -> "ADWriterFactory[NDPluginFileIO]":
        """Create a factory for a JPEG file writer.

        :param path_provider: Provides file path information for each acquisition.
        :param writer_suffix: PV suffix for the NDPluginFile plugin, defaults to
            ``JPEG1:``.
        :param writer_name:
            Attribute name for the writer on the detector, defaults to
            ``"jpeg"``.
        :param datakey_suffix: Suffix appended to the datakey name, defaults to ``""``.
        :param array_description:
            Override the array shape/type description built from the driver.
            Pass an `NDArrayDescription` or a callable ``(driver) → NDArrayDescription``
            when the shape/type comes from a plugin.
        """
        return ADWriterFactory(
            writer_cls=NDPluginFileIO,
            writer_suffix=writer_suffix,
            writer_name=writer_name,
            datakey_suffix=datakey_suffix,
            array_description=array_description,
            data_logic_factory=lambda writer, desc, driver, plugins: (
                ADMultipartDataLogic(
                    array_description=desc,
                    path_provider=path_provider,
                    writer=writer,
                    extension=".jpg",
                    mimetype="multipart/related;type=image/jpeg",
                    datakey_suffix=datakey_suffix,
                )
            ),
        )

    @staticmethod
    def tiff(
        path_provider: PathProvider,
        writer_suffix: str = "TIFF1:",
        writer_name: str = "tiff",
        datakey_suffix: str = "",
        array_description: NDArrayDescription
        | Callable[[ADBaseIO], NDArrayDescription]
        | None = None,
    ) -> "ADWriterFactory[NDPluginFileIO]":
        """Create a factory for a TIFF file writer.

        :param path_provider: Provides file path information for each acquisition.
        :param writer_suffix: PV suffix for the NDPluginFile plugin, defaults to
            ``TIFF1:``.
        :param writer_name:
            Attribute name for the writer on the detector, defaults to
            ``"tiff"``.
        :param datakey_suffix: Suffix appended to the datakey name, defaults to ``""``.
        :param array_description:
            Override the array shape/type description built from the driver.
            Pass an `NDArrayDescription` or a callable ``(driver) → NDArrayDescription``
            when the shape/type comes from a plugin.
        """
        return ADWriterFactory(
            writer_cls=NDPluginFileIO,
            writer_suffix=writer_suffix,
            writer_name=writer_name,
            datakey_suffix=datakey_suffix,
            array_description=array_description,
            data_logic_factory=lambda writer, desc, driver, plugins: (
                ADMultipartDataLogic(
                    array_description=desc,
                    path_provider=path_provider,
                    writer=writer,
                    extension=".tiff",
                    mimetype="multipart/related;type=image/tiff",
                    datakey_suffix=datakey_suffix,
                )
            ),
        )
