from pathlib import Path
from typing import Iterator, List

from event_model import StreamDatum, StreamResource, compose_stream_resource

from ophyd_async.core import PathInfo

from ophyd_async.epics.areadetector.writers.general_hdffile import _HDFDataset


class _HDFFile:
    """
    :param path_info: Contains information about how to construct a StreamResource
    :param full_file_name: Absolute path to the file to be written
    :param datasets: Datasets to write into the file
    """

    def __init__(
        self,
        path_info: PathInfo,
        full_file_name: Path,
        datasets: List[_HDFDataset],
    ) -> None:
        self._last_emitted = 0
        self._bundles = [
            compose_stream_resource(
                mimetype="application/x-hdf5",
                uri=f"file://localhost{full_file_name}",
                data_key=ds.name,
                parameters={
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
        if indices_written > self._last_emitted:
            indices = {
                "start": self._last_emitted,
                "stop": indices_written,
            }
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield bundle.compose_stream_datum(indices)
        return None
