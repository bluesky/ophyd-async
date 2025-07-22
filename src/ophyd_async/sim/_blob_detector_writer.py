from collections.abc import AsyncGenerator, AsyncIterator

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
        self.composer: HDFDocumentComposer | None = None
        self.datasets: list[HDFDatasetDescription] = []

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        path_info = self.path_provider(name)
        write_path = path_info.directory_path / f"{path_info.filename}.h5"
        read_path_uri = f"{path_info.directory_uri}{path_info.filename}.h5"
        self.pattern_generator.open_file(write_path, WIDTH, HEIGHT)
        self.exposures_per_event = exposures_per_event
        # We know it will write data and sum, so emit those
        self.datasets = [
            HDFDatasetDescription(
                data_key=name,
                dataset=DATA_PATH,
                shape=(exposures_per_event, HEIGHT, WIDTH),
                dtype_numpy=np.dtype(np.uint8).str,
                chunk_shape=(1024,),
            ),
            HDFDatasetDescription(
                data_key=f"{name}-sum",
                dataset=SUM_PATH,
                shape=(exposures_per_event,) if exposures_per_event > 1 else (),
                dtype_numpy=np.dtype(np.int64).str,
                chunk_shape=(1024,),
            ),
        ]
        self.composer = HDFDocumentComposer(read_path_uri, self.datasets)
        describe = {
            ds.data_key: DataKey(
                source="sim://pattern-generator-hdf-file",
                shape=list(ds.shape),
                dtype="array"
                if exposures_per_event > 1 or len(ds.shape) > 1
                else "number",
                dtype_numpy=ds.dtype_numpy,
                external="STREAM:",
            )
            for ds in self.datasets
        }
        return describe

    def get_hints(self, name: str) -> Hints:
        """The hints to be used for the detector."""
        return {"fields": [name]}

    async def get_indices_written(self) -> int:
        return self.pattern_generator.get_last_index() // self.exposures_per_event

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        while True:
            yield self.pattern_generator.get_last_index() // self.exposures_per_event
            await self.pattern_generator.wait_for_next_index(timeout)

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # When we have written something to the file
        if self.composer is None:
            msg = f"open() not called on {self}"
            raise RuntimeError(msg)
        for doc in self.composer.make_stream_docs(indices_written):
            yield doc

    async def close(self) -> None:
        self.pattern_generator.close_file()
