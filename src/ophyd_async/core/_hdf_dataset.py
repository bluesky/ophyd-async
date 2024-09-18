from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlunparse

from event_model import (
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamDatum,
    StreamRange,
    StreamResource,
)


@dataclass
class HDFDataset:
    data_key: str
    dataset: str
    shape: Sequence[int] = field(default_factory=tuple)
    dtype_numpy: str = ""
    multiplier: int = 1
    swmr: bool = False
    # Represents explicit chunk size written to disk.
    chunk_shape: tuple[int, ...] = ()


SLICE_NAME = "AD_HDF5_SWMR_SLICE"


class HDFFile:
    """
    :param full_file_name: Absolute path to the file to be written
    :param datasets: Datasets to write into the file
    """

    def __init__(
        self,
        full_file_name: Path,
        datasets: list[HDFDataset],
        hostname: str = "localhost",
    ) -> None:
        self._last_emitted = 0
        self._hostname = hostname

        if len(datasets) == 0:
            self._bundles = []
            return None

        bundler_composer = ComposeStreamResource()

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

        self._bundles: list[ComposeStreamResourceBundle] = [
            bundler_composer(
                mimetype="application/x-hdf5",
                uri=uri,
                data_key=ds.data_key,
                parameters={
                    "dataset": ds.dataset,
                    "swmr": ds.swmr,
                    "multiplier": ds.multiplier,
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
