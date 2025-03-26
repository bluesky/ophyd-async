import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from xml.etree import ElementTree as ET

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DatasetDescriber,
    HDFDatasetDescription,
    HDFDocumentComposer,
    PathProvider,
)

from ._core_io import NDFileHDFIO, NDPluginBaseIO
from ._core_writer import ADWriter
from ._utils import (
    convert_param_dtype_to_np,
    convert_pv_dtype_to_np,
)


class ADHDFWriter(ADWriter[NDFileHDFIO]):
    """Allow `NDFileHDFIO` to be used within `StandardDetector`."""

    default_suffix: str = "HDF1:"

    def __init__(
        self,
        fileio: NDFileHDFIO,
        path_provider: PathProvider,
        dataset_describer: DatasetDescriber,
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        super().__init__(
            fileio,
            path_provider,
            dataset_describer,
            plugins=plugins,
            file_extension=".h5",
            mimetype="application/x-hdf5",
        )
        self._datasets: list[HDFDatasetDescription] = []
        self._composer: HDFDocumentComposer | None = None
        self._filename_template = "%s%s"

    async def open(self, name: str, multiplier: int = 1) -> dict[str, DataKey]:
        self._composer = None

        # Setting HDF writer specific signals

        # Make sure we are using chunk auto-sizing
        await asyncio.gather(self.fileio.chunk_size_auto.set(True))

        await asyncio.gather(
            self.fileio.num_extra_dims.set(0),
            self.fileio.lazy_open.set(True),
            self.fileio.swmr_mode.set(True),
            self.fileio.xml_file_name.set(""),
        )

        # Set common AD file plugin params, begin capturing
        await self.begin_capture()

        name = self._name_provider()
        detector_shape = await self._dataset_describer.shape()
        np_dtype = await self._dataset_describer.np_datatype()
        self._multiplier = multiplier
        outer_shape = (multiplier,) if multiplier > 1 else ()

        # Determine number of frames that will be saved per HDF chunk
        frames_per_chunk = await self.fileio.num_frames_chunks.get_value()

        # Add the main data
        self._datasets = [
            HDFDatasetDescription(
                data_key=name,
                dataset="/entry/data/data",
                shape=detector_shape,
                dtype_numpy=np_dtype,
                multiplier=multiplier,
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
                            shape=(),
                            dtype_numpy=np_datatype,
                            # NDAttributes appear to always be configured with
                            # this chunk size
                            chunk_shape=(16384,),
                            multiplier=multiplier,
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
            if not self._composer:
                path = Path(await self.fileio.full_file_name.get_value())
                self._composer = HDFDocumentComposer(
                    # See https://github.com/bluesky/ophyd-async/issues/122
                    path,
                    self._datasets,
                )
                # stream resource says "here is a dataset",
                # stream datum says "here are N frames in that stream resource",
                # you get one stream resource and many stream datums per scan

                for doc in self._composer.stream_resources():
                    yield "stream_resource", doc
            for doc in self._composer.stream_data(indices_written):
                yield "stream_datum", doc
