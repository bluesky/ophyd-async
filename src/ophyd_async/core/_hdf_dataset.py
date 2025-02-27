from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlunparse

from event_model import (  # type: ignore
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamDatum,
    StreamRange,
    StreamResource,
)
from pydantic import BaseModel, Field


class HDFDatasetDescription(BaseModel):
    """A description of the type and shape of a dataset in an HDF file."""

    data_key: str
    """The data_key that will appear in the event descriptor,
    e.g. det or det.data"""

    dataset: str
    """The dataset name within the HDF file,
    e.g. /entry/data/data or /entry/instrument/NDAttributes/sum"""

    shape: tuple[int, ...] = Field(default_factory=tuple)
    """The shape of a single event's data in the HDF file,
    e.g. (1, 768, 1024) for arrays or () for scalars"""

    dtype_numpy: str = ""
    """The numpy dtype for this field,
    e.g. <i2 or <f8"""

    chunk_shape: tuple[int, ...]
    """The explicit chunk size written to disk"""


SLICE_NAME = "AD_HDF5_SWMR_SLICE"


class HDFDocumentComposer:
    """A helper class to make stream resource and datums for HDF datasets.

    :param full_file_name: Absolute path to the file that has been written
    :param datasets: Descriptions of each of the datasets that will appear in the file
    """

    def __init__(
        self,
        full_file_name: Path,
        datasets: list[HDFDatasetDescription],
        hostname: str = "localhost",
    ) -> None:
        self._last_emitted = 0
        self._hostname = hostname
        uri = urlunparse(
            (
                "file",
                self._hostname,
                str(full_file_name.absolute()),
                "",
                "",
                None,
            )
        )
        bundler_composer = ComposeStreamResource()
        self._bundles: list[ComposeStreamResourceBundle] = [
            bundler_composer(
                mimetype="application/x-hdf5",
                uri=uri,
                data_key=ds.data_key,
                parameters={
                    "dataset": ds.dataset,
                    "chunk_shape": ds.chunk_shape,
                },
                uid=None,
                validate=True,
            )
            for ds in datasets
        ]

    def stream_resources(self) -> Iterator[StreamResource]:
        for bundle in self._bundles:
            yield bundle.stream_resource_doc

    def stream_data(self, indices_written: int) -> Iterator[StreamDatum]:
        # Indices are relative to resource
        if indices_written > self._last_emitted:
            indices: StreamRange = {
                "start": self._last_emitted,
                "stop": indices_written,
            }
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield bundle.compose_stream_datum(indices)
