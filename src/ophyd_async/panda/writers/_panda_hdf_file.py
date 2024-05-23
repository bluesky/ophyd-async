from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List

from event_model import StreamDatum, StreamResource, compose_stream_resource

from ophyd_async.core import PathInfo


@dataclass
class _HDFDataset:
    device_name: str
    block: str
    name: str
    path: str
    shape: List[int]
    multiplier: int


class _HDFFile:
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
                uri=f"file://{full_file_name}",
                # spec="AD_HDF5_SWMR_SLICE",
                # root=str(path_info.root),
                data_key=ds.name,
                # resource_path=(f"{str(path_info.root)}/{full_file_name}"),
                parameters={
                    "name": ds.name,
                    "block": ds.block,
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
