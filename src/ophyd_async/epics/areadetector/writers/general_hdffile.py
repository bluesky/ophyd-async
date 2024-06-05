from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional

import event_model
from event_model import (
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamDatum,
    StreamResource,
)

from ophyd_async.core import DirectoryInfo


@dataclass
class _HDFDataset:
    name: str
    shape: Optional[List[int]] = None
    multiplier: Optional[int] = 1
    path: Optional[str] = None
    device_name: Optional[str] = None
    block: Optional[str] = None
    maxshape: tuple[Any, ...] = (None,)
    dtype: Optional[Any] = None
    fillvalue: Optional[int] = None


SLICE_NAME = "AD_HDF5_SWMR_SLICE"


def versiontuple(v):
    return tuple(map(int, (v.split("."))))


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
        if len(datasets) == 0:
            self._bundles = []
            return None

        if versiontuple(event_model.__version__) < versiontuple("1.21.0"):
            print("OHHHHH HEREEEEEEEEEEE")

            path = f"{str(directory_info.root)}/{full_file_name}"
            root = str(directory_info.root)
            bundler_composer = ComposeStreamResource()

            self._bundles: List[ComposeStreamResourceBundle] = [
                bundler_composer(
                    spec=SLICE_NAME,
                    root=root,
                    resource_path=path,
                    data_key=ds.name.replace("/", "_"),
                    resource_kwargs={
                        "name": ds.name,
                        "block": ds.block,
                        "path": ds.path,
                        "shape": ds.shape,
                        "multiplier": ds.multiplier,
                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                    },
                )
                for ds in datasets
            ]
        else:
            print("HEREEEEEEEEEEE")
            path = f"{str(directory_info.root)}/{full_file_name}"
            root = str(directory_info.root)
            bundler_composer = ComposeStreamResource()

            self._bundles: List[ComposeStreamResourceBundle] = [
                bundler_composer(
                    mimetype="application/x-hdf5",
                    uri=path,
                    data_key=ds.name.replace("/", "_"),
                    parameters={
                        "name": ds.name,
                        "block": ds.block,
                        "path": ds.path,
                        "shape": ds.shape,
                        "multiplier": ds.multiplier,
                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
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
