import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from xml.etree import ElementTree as ET

from bluesky.protocols import Hints, StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DatasetDescriber,
    DetectorWriter,
    HDFDataset,
    HDFFile,
    NameProvider,
    PathProvider,
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)

from ._core_io import NDArrayBaseIO, NDFileHDFIO
from ._utils import (
    FileWriteMode,
    convert_param_dtype_to_np,
    convert_pv_dtype_to_np,
)


class ADHDFWriter(DetectorWriter):
    def __init__(
        self,
        hdf: NDFileHDFIO,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
        *plugins: NDArrayBaseIO,
    ) -> None:
        self.hdf = hdf
        self._path_provider = path_provider
        self._name_provider = name_provider
        self._dataset_describer = dataset_describer

        self._plugins = plugins
        self._capture_status: AsyncStatus | None = None
        self._datasets: list[HDFDataset] = []
        self._file: HDFFile | None = None
        self._multiplier = 1

    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        self._file = None
        info = self._path_provider(device_name=self._name_provider())

        # Set the directory creation depth first, since dir creation callback happens
        # when directory path PV is processed.
        await self.hdf.create_directory.set(info.create_dir_depth)

        # Make sure we are using chunk auto-sizing
        await asyncio.gather(self.hdf.chunk_size_auto.set(True))

        await asyncio.gather(
            self.hdf.num_extra_dims.set(0),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.hdf.file_path.set(str(info.directory_path)),
            self.hdf.file_name.set(info.filename),
            self.hdf.file_template.set("%s/%s.h5"),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
            # Never use custom xml layout file but use the one defined
            # in the source code file NDFileHDF5LayoutXML.cpp
            self.hdf.xml_file_name.set(""),
        )

        assert (
            await self.hdf.file_path_exists.get_value()
        ), f"File path {info.directory_path} for hdf plugin does not exist"

        # Overwrite num_capture to go forever
        await self.hdf.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.hdf.capture, True)
        name = self._name_provider()
        detector_shape = await self._dataset_describer.shape()
        np_dtype = await self._dataset_describer.np_datatype()
        self._multiplier = multiplier
        outer_shape = (multiplier,) if multiplier > 1 else ()

        # Determine number of frames that will be saved per HDF chunk
        frames_per_chunk = await self.hdf.num_frames_chunks.get_value()

        # Add the main data
        self._datasets = [
            HDFDataset(
                data_key=name,
                dataset="/entry/data/data",
                shape=detector_shape,
                dtype_numpy=np_dtype,
                multiplier=multiplier,
                chunk_shape=(frames_per_chunk, *detector_shape),
            )
        ]
        # And all the scalar datasets
        for plugin in self._plugins:
            maybe_xml = await plugin.nd_attributes_file.get_value()
            # This is the check that ADCore does to see if it is an XML string
            # rather than a filename to parse
            if "<Attributes>" in maybe_xml:
                root = ET.fromstring(maybe_xml)
                for child in root:
                    datakey = child.attrib["name"]
                    if child.attrib.get("type", "EPICS_PV") == "EPICS_PV":
                        np_datatype = convert_pv_dtype_to_np(
                            child.attrib.get("dbrtype", "DBR_NATIVE")
                        )
                    else:
                        np_datatype = convert_param_dtype_to_np(
                            child.attrib.get("datatype", "INT")
                        )
                    self._datasets.append(
                        HDFDataset(
                            datakey,
                            f"/entry/instrument/NDAttributes/{datakey}",
                            (),
                            np_datatype,
                            multiplier,
                            # NDAttributes appear to always be configured with
                            # this chunk size
                            chunk_shape=(16384,),
                        )
                    )

        describe = {
            ds.data_key: DataKey(
                source=self.hdf.full_file_name.source,
                shape=outer_shape + tuple(ds.shape),
                dtype="array" if ds.shape else "number",
                dtype_numpy=ds.dtype_numpy,  # type: ignore
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(self.hdf.num_captured, timeout):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self.hdf.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        await self.hdf.flush_now.set(True)
        if indices_written:
            if not self._file:
                path = Path(await self.hdf.full_file_name.get_value())
                self._file = HDFFile(
                    # See https://github.com/bluesky/ophyd-async/issues/122
                    path,
                    self._datasets,
                )
                # stream resource says "here is a dataset",
                # stream datum says "here are N frames in that stream resource",
                # you get one stream resource and many stream datums per scan

                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(False, wait=False)
        await wait_for_value(self.hdf.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
