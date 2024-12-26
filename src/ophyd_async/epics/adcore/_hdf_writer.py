import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from xml.etree import ElementTree as ET

from bluesky.protocols import Hints, StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DatasetDescriber,
    HDFDataset,
    HDFFile,
    NameProvider,
    PathProvider,
    wait_for_value,
)

from ._core_io import NDFileHDFIO, NDPluginBaseIO
from ._core_writer import ADWriter
from ._utils import (
    convert_param_dtype_to_np,
    convert_pv_dtype_to_np,
)


class ADHDFWriter(ADWriter[NDFileHDFIO]):
    default_suffix: str = "HDF1:"

    def __init__(
        self,
        fileio: NDFileHDFIO,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        super().__init__(
            fileio,
            path_provider,
            name_provider,
            dataset_describer,
            plugins=plugins,
            file_extension=".h5",
            mimetype="application/x-hdf5",
        )
        self._datasets: list[HDFDataset] = []
        self._file: HDFFile | None = None
        self._include_file_number = False

    async def open(self, frequency_ratio: int = 1) -> dict[str, DataKey]:
        self._file = None

        # Setting HDF writer specific signals

        # Make sure we are using chunk auto-sizing
        await asyncio.gather(self.fileio.chunk_size_auto.set(True))

        await asyncio.gather(
            self.fileio.num_extra_dims.set(0),
            self.fileio.lazy_open.set(True),
            self.fileio.swmr_mode.set(True),
            self.fileio.xml_file_name.set(""),
        )

        # By default, don't add file number to filename
        self._filename_template = "%s%s"
        if self._include_file_number:
            self._filename_template += "_%6.6d"

        # Set common AD file plugin params, begin capturing
        await self.begin_capture()

        name = self._name_provider()
        detector_shape = await self._dataset_describer.shape()
        np_dtype = await self._dataset_describer.np_datatype()
        self._frequency_ratio = frequency_ratio

        # Determine number of frames that will be saved per HDF chunk
        frames_per_chunk = await self.fileio.num_frames_chunks.get_value()

        # Add the main data
        self._datasets = [
            HDFDataset(
                data_key=name,
                dataset="/entry/data/data",
                shape=detector_shape,
                dtype_numpy=np_dtype,
                frequency_ratio=frequency_ratio,
                chunk_shape=(frames_per_chunk, *detector_shape),
            )
        ]
        # And all the scalar datasets
        for plugin in self._plugins.values():
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
                source=self.fileio.full_file_name.source,
                shape=list(outer_shape + tuple(ds.shape)),
                dtype="array" if ds.shape else "number",
                dtype_numpy=ds.dtype_numpy,
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        await self.fileio.flush_now.set(True)
        if indices_written:
            if not self._file:
                path = Path(await self.fileio.full_file_name.get_value())
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
        await self.fileio.capture.set(False, wait=False)
        await wait_for_value(self.fileio.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
