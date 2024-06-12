from pathlib import Path
from typing import Iterator, List

from event_model import StreamDatum, StreamResource, compose_stream_resource

from ophyd_async.core import DirectoryInfo

from ._hdfdataset import _HDFDataset


class _HDFFile:
    """
    :param directory_info: Contains information about how to construct a StreamResource
    :param full_file_name: Absolute path to the file to be written
    :param datasets: Datasets to write into the file
    """

    def __init__(
        self,
        directory_info: DirectoryInfo,
        full_file_name: Path,
        datasets: List[_HDFDataset],
    ) -> None:
        self._last_emitted = 0
        self._bundles = [
            compose_stream_resource(
                spec="AD_HDF5_SWMR_SLICE",
                root=str(directory_info.root),
                data_key=ds.name,
                resource_path=str(full_file_name.relative_to(directory_info.root)),
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
        if indices_written > self._last_emitted:
            indices = {
                "start": self._last_emitted,
                "stop": indices_written,
            }
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield bundle.compose_stream_datum(indices)
        return None
