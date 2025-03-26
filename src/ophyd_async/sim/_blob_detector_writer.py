from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

import numpy as np
from bluesky.protocols import Hints, StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DetectorWriter,
    HDFDatasetDescription,
    HDFDocumentComposer,
    PathProvider,
)

from ._pattern_generator import DATA_PATH, SUM_PATH, PatternGenerator

WIDTH = 320
HEIGHT = 240


class BlobDetectorWriter(DetectorWriter):
    def __init__(
        self,
        pattern_generator: PatternGenerator,
        path_provider: PathProvider,
    ) -> None:
        self.pattern_generator = pattern_generator
        self.path_provider = path_provider
        self.path: Path | None = None
        self.composer: HDFDocumentComposer | None = None
        self.datasets: list[HDFDatasetDescription] = []

    async def open(self, name: str, multiplier: int = 1) -> dict[str, DataKey]:
        name = self.name_provider()
        path_info = self.path_provider(name)
        self.path = path_info.directory_path / f"{path_info.filename}.h5"
        self.pattern_generator.open_file(self.path, WIDTH, HEIGHT)
        # We know it will write data and sum, so emit those
        self.datasets = [
            HDFDatasetDescription(
                data_key=name,
                dataset=DATA_PATH,
                shape=(HEIGHT, WIDTH),
                dtype_numpy=np.dtype(np.uint8).str,
                chunk_shape=(HEIGHT, WIDTH),
                multiplier=multiplier,
            ),
            HDFDatasetDescription(
                data_key=f"{name}-sum",
                dataset=SUM_PATH,
                shape=(),
                dtype_numpy=np.dtype(np.int64).str,
                multiplier=multiplier,
                chunk_shape=(1024,),
            ),
        ]
        self.composer = None
        outer_shape = (multiplier,) if multiplier > 1 else ()
        describe = {
            ds.data_key: DataKey(
                source="sim://pattern-generator-hdf-file",
                shape=list(outer_shape) + list(ds.shape),
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self.datasets
        }
        return describe

    def get_hints(self, name: str) -> Hints:
        """The hints to be used for the detector."""
        return {"fields": [name]}

    async def get_indices_written(self) -> int:
        return self.pattern_generator.get_last_index()

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        while True:
            yield self.pattern_generator.get_last_index()
            await self.pattern_generator.wait_for_next_index(timeout)

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # When we have written something to the file
        if indices_written:
            # Only emit stream resource the first time we see frames in
            # the file
            if not self.composer:
                if not self.path:
                    raise RuntimeError(f"open() not called on {self}")
                self.composer = HDFDocumentComposer(self.path, self.datasets)
                for doc in self.composer.stream_resources():
                    yield "stream_resource", doc
            for doc in self.composer.stream_data(indices_written):
                yield "stream_datum", doc

    async def close(self) -> None:
        self.pattern_generator.close_file()
