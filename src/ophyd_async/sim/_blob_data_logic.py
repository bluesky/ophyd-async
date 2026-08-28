from collections.abc import Sequence
from pathlib import PurePath

import numpy as np

from ophyd_async.core import (
    DetectorDataLogic,
    PathProvider,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    error_if_none,
)

from ._pattern_generator import DATA_PATH, SUM_PATH, PatternGenerator

WIDTH = 320
HEIGHT = 240


class BlobDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        pattern_generator: PatternGenerator,
    ):
        self.path_provider = path_provider
        self.pattern_generator = pattern_generator
        # Where make_data_provider decided to write, for start to open
        self._to_open: PurePath | None = None

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> StreamableDataProvider:
        # The sim blob writer uses a fixed chunk shape and writes for as long as
        # it is told to, so neither the period nor the count is needed.
        del period, num_collections
        # Work out where to write
        path_info = self.path_provider(datakey_name)
        self._to_open = path_info.directory_path / f"{path_info.filename}.h5"
        # Describe what we would write
        data_resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=(HEIGHT, WIDTH),
            # NDAttributes appear to always be configured with
            # this chunk size
            chunk_shape=(1, HEIGHT, WIDTH),
            dtype_numpy=np.dtype(np.uint8).str,
            parameters={"dataset": DATA_PATH},
        )
        sum_resource = StreamResourceInfo(
            data_key=f"{datakey_name}-sum",
            shape=(),
            # NDAttributes appear to always be configured with
            # this chunk size
            chunk_shape=(1024,),
            dtype_numpy=np.dtype(np.int64).str,
            parameters={"dataset": SUM_PATH},
        )
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{path_info.filename}.h5",
            resources=[data_resource, sum_resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.pattern_generator.images_written,
        )

    async def start(self) -> None:
        write_path = error_if_none(
            self._to_open, "make_data_provider() has not been called"
        )
        self.pattern_generator.open_file(write_path, WIDTH, HEIGHT)

    async def stop(self) -> None:
        self.pattern_generator.close_file()

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        # The main dataset is always hinted
        return [datakey_name]
