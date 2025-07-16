import asyncio
from collections.abc import AsyncIterator
from typing import TypeGuard
from xml.etree import ElementTree as ET

from bluesky.protocols import StreamAsset
from event_model import DataKey
from pydantic import PositiveInt

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


def _is_fully_described(shape: tuple[int | None, ...]) -> TypeGuard[tuple[int, ...]]:
    return None not in shape


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

    async def open(
        self, name: str, exposures_per_event: PositiveInt = 1
    ) -> dict[str, DataKey]:
        # Setting HDF writer specific signals
        # Make sure we are using chunk auto-sizing
        await asyncio.gather(self.fileio.chunk_size_auto.set(True))

        await asyncio.gather(
            self.fileio.num_extra_dims.set(0),
            self.fileio.lazy_open.set(True),
            self.fileio.swmr_mode.set(True),
            self.fileio.xml_file_name.set(""),
        )

        self._path_info = self._path_provider(device_name=name)

        # Set common AD file plugin params, begin capturing
        await self._begin_capture(name)

        detector_shape = await self._dataset_describer.shape()
        np_dtype = await self._dataset_describer.np_datatype()

        # Used by the base class
        self._exposures_per_event = exposures_per_event

        # Determine number of frames that will be saved per HDF chunk
        frames_per_chunk = await self.fileio.num_frames_chunks.get_value()

        if not _is_fully_described(detector_shape):
            # Questions:
            # - Can AreaDetector support this?
            # - How to deal with chunking?
            # Don't support for now - leave option open to support it later
            raise ValueError(
                "Datasets with partially unknown dimensionality "
                "are not currently supported by ADHDFWriter."
            )

        # Add the main data
        self._datasets = [
            HDFDatasetDescription(
                data_key=name,
                dataset="/entry/data/data",
                shape=(exposures_per_event, *detector_shape),
                dtype_numpy=np_dtype,
                chunk_shape=(frames_per_chunk, *detector_shape),
            )
        ]

        self._composer = HDFDocumentComposer(
            # See https://github.com/bluesky/ophyd-async/issues/122
            f"{self._path_info.directory_uri}{self._path_info.filename}{self._file_extension}",
            self._datasets,
        )

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
                            shape=(exposures_per_event,)
                            if exposures_per_event > 1
                            else (),
                            dtype_numpy=np_datatype,
                            # NDAttributes appear to always be configured with
                            # this chunk size
                            chunk_shape=(16384,),
                        )
                    )

        describe = {
            ds.data_key: DataKey(
                source=self.fileio.full_file_name.source,
                shape=list(ds.shape),
                dtype="array"
                if exposures_per_event > 1 or len(ds.shape) > 1
                else "number",
                dtype_numpy=ds.dtype_numpy,
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if self._composer is None:
            msg = f"open() not called on {self}"
            raise RuntimeError(msg)
        await self.fileio.flush_now.set(True)
        for doc in self._composer.make_stream_docs(indices_written):
            yield doc
