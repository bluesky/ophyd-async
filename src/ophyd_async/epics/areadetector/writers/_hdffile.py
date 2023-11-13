import time
from typing import Iterator, List

from event_model import StreamDatum, StreamResource, compose_stream_resource

from ._hdfdataset import _HDFDataset

FRAME_TIMEOUT = 120


class _HDFFile:
    def __init__(self, full_file_name: str, datasets: List[_HDFDataset]) -> None:
        self._last_emitted = 0
        self._last_flush = 0.0
        self._bundles = [
            compose_stream_resource(
                spec="AD_HDF5_SWMR_SLICE",
                root="/",
                data_key=ds.name,
                resource_path=full_file_name,
                resource_kwargs={
                    "path": ds.path,
                    "multiplier": ds.multiplier,
                    "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                },
            )
            for ds in datasets
        ]

    def stream_resources(self) -> Iterator[StreamResource]:
        for bundle in self._bundles:
            yield bundle.stream_resource_doc

    def stream_data(self, indices_written: int) -> Iterator[StreamDatum]:
        # Indices are relative to resource
        indices = dict(
            start=self._last_emitted,
            stop=indices_written,
        )
        self._last_emitted = indices_written
        self._last_flush = time.monotonic()
        for bundle in self._bundles:
            yield bundle.compose_stream_datum(indices)
