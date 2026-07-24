from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any

from bluesky.protocols import StreamAsset
from event_model import ComposeStreamResource, DataKey, StreamRange
from event_model.documents import PartialEventPage

from ._signal import SignalR, SignalW
from ._utils import ConfinedModel


class StreamableDataProvider:
    collections_written_signal: SignalR[int]

    @abstractmethod
    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        """Return a DataKey for each Signal that produces a Reading.

        Called before the first exposure is taken.

        :param collections_per_event: this should appear in the shape of each DataKey
        """

    async def make_stream_docs(
        self, collections_written: int, collections_per_event: int
    ) -> AsyncIterator[StreamAsset]:
        """Make StreamAsset documents up to the given index.

        Default implementation is a no-op. Subclasses should override this
        to emit actual StreamAsset documents.
        """
        while False:
            yield


class PageableDataProvider:
    """For bounded data held in a finite buffer, emitted as event pages.

    Used by data logics whose device must be told how many collections to
    expect before it starts acquiring, because it holds a finite buffer that
    has to be sized upfront: an areaDetector stats time series (`TSNumPoints`),
    or a scaler whose MCA array length is the frame count. Such a device
    produces its data as event pages at the end of an event rather than as
    stream datums as it goes.

    A step-scan event has a single collection window, so `make_pages` yields
    one page of one event, which `StandardDetector.read` extracts to a single
    reading; the same `make_pages` serves fly-scan collection.
    """

    collections_written_signal: SignalR[int]

    @abstractmethod
    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        """Return a DataKey for each field this provider produces.

        Called before the first exposure is taken.

        :param collections_per_event: this should appear in the shape of each DataKey
        """

    @abstractmethod
    def make_pages(
        self, collections_written: int, collections_per_event: int
    ) -> AsyncIterator[PartialEventPage]:
        """Emit event pages for collections written since the last call.

        :param collections_written: how many collections have been written so far
        :param collections_per_event: how many collections make up one event
        """


class StreamResourceInfo(ConfinedModel):
    """A description of a single StreamResource that should be emitted."""

    data_key: str
    """The data_key that will appear in the event descriptor,
    e.g. det or det.data"""

    shape: tuple[int | None, ...]
    """The shape of a single collection's data in the HDF file,
    e.g. (768, 1024) for arrays or () for scalars"""

    chunk_shape: tuple[int, ...]
    """The explicit chunk size written to disk"""

    dtype_numpy: str
    """The numpy dtype for this field,
    e.g. <i2 or <f8"""

    parameters: dict[str, Any]
    """Any other parameters that should be included in the StreamResource,
    e.g. dataset path"""

    source: str = ""
    """The source string that should appear in the event descriptor, blank means use uri
    e.g. ca://HDF:FullFileName_RBV"""


class StreamResourceDataProvider(StreamableDataProvider):
    """A helper class to make stream resource and datums for HDF datasets.

    :param full_file_name: Absolute path to the file that has been written
    :param datasets: Descriptions of each of the datasets that will appear in the file
    """

    def __init__(
        self,
        uri: str,
        resources: Sequence[StreamResourceInfo],
        mimetype: str,
        collections_written_signal: SignalR[int],
        flush_signal: SignalW[bool] | None = None,
    ) -> None:
        self.uri = uri
        self.resources = list(resources)
        self.collections_written_signal = collections_written_signal
        self.flush_signal = flush_signal
        self.last_emitted = 0
        bundler_composer = ComposeStreamResource()
        self.bundles = [
            bundler_composer(
                mimetype=mimetype,
                uri=uri,
                data_key=resource.data_key,
                parameters={
                    "chunk_shape": resource.chunk_shape,
                    **resource.parameters,
                },
                uid=None,
                validate=True,
            )
            for resource in self.resources
        ]

    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        describe = {
            resource.data_key: DataKey(
                source=resource.source or self.uri,
                shape=[collections_per_event, *resource.shape],
                dtype="array"
                if collections_per_event > 1 or len(resource.shape) > 1
                else "number",
                dtype_numpy=resource.dtype_numpy,
                external="STREAM:",
            )
            for resource in self.resources
        }
        return describe

    async def make_stream_docs(
        self, collections_written: int, collections_per_event: int
    ) -> AsyncIterator[StreamAsset]:
        if self.flush_signal:
            await self.flush_signal.set(True)
        # TODO: fail if we get dropped frames
        indices_written = collections_written // collections_per_event
        if indices_written and not self.last_emitted:
            for bundle in self.bundles:
                yield "stream_resource", bundle.stream_resource_doc

        if indices_written > self.last_emitted:
            indices: StreamRange = {
                "start": self.last_emitted,
                "stop": indices_written,
            }
            self.last_emitted = indices_written
            for bundle in self.bundles:
                yield "stream_datum", bundle.compose_stream_datum(indices)
