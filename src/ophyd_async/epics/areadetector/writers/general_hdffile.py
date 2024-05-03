from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Union

from event_model import (
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamDatum,
    StreamResource,
    compose_stream_resource,
)

from ophyd_async.core import DirectoryInfo


@dataclass
class DatasetConfig:
    name: str
    shape: Sequence[int]
    maxshape: tuple[Any, ...] = (None,)
    path: Optional[str] = None
    multiplier: Optional[int] = 1
    dtype: Optional[Any] = None
    fillvalue: Optional[int] = None


@dataclass
class _HDFDataset:
    name: str
    path: str
    shape: List[int]
    multiplier: int
    device_name: Optional[str] = None
    block: Optional[str] = None


SLICE_NAME = "AD_HDF5_SWMR_SLICE"


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
        datasets: Union[List[_HDFDataset], List[DatasetConfig]],
    ) -> None:
        self._last_emitted = 0
        if len(datasets) == 0:
            self._bundles = []
            return None

        if isinstance(datasets[0], _HDFDataset):
            self._bundles = [
                compose_stream_resource(
                    spec=SLICE_NAME,
                    root=str(directory_info.root),
                    data_key=ds.name,
                    # resource_path=(f"{str(directory_info.root)}/{full_file_name}"),
                    resource_path=str(full_file_name.relative_to(directory_info.root)),
                    resource_kwargs={
                        "name": ds.name,
                        "block": ds.block,
                        "path": ds.path,
                        "multiplier": ds.multiplier,
                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                    },
                )
                for ds in datasets
            ]
        else:
            path = str(full_file_name.relative_to(directory_info.root))
            root = str(directory_info.root)
            bundler_composer = ComposeStreamResource()

            self._bundles: List[ComposeStreamResourceBundle] = [
                bundler_composer(
                    spec=SLICE_NAME,
                    root=root,
                    resource_path=path,
                    data_key=ds.name.replace("/", "_"),
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

    def close(self) -> None:
        for bundle in self._bundles:
            bundle.close()
