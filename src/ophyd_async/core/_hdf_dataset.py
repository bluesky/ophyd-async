from collections.abc import Iterator

from bluesky.protocols import StreamAsset
from event_model import (  # type: ignore
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamRange,
)
from pydantic import Field

from ._utils import ConfinedModel


class HDFDatasetDescription(ConfinedModel):
    """A description of the type and shape of a dataset in an HDF file."""

    data_key: str
    """The data_key that will appear in the event descriptor,
    e.g. det or det.data"""

    dataset: str
    """The dataset name within the HDF file,
    e.g. /entry/data/data or /entry/instrument/NDAttributes/sum"""

    shape: tuple[int | None, ...] = Field(default_factory=tuple)
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
        file_uri: str,
        datasets: list[HDFDatasetDescription],
    ) -> None:
        self._last_emitted = 0
        uri = file_uri
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

    def make_stream_docs(self, indices_written: int) -> Iterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if indices_written and not self._last_emitted:
            for bundle in self._bundles:
                yield "stream_resource", bundle.stream_resource_doc

        if indices_written > self._last_emitted:
            indices: StreamRange = {
                "start": self._last_emitted,
                "stop": indices_written,
            }
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield "stream_datum", bundle.compose_stream_datum(indices)
