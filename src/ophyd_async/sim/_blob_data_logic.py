from collections.abc import Sequence

import numpy as np

from ophyd_async.core import (
    DetectorDataLogic,
    PathProvider,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
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

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(detector_name)
        # Open the file
        write_path = path_info.directory_path / f"{path_info.filename}.h5"
        self.pattern_generator.open_file(write_path, WIDTH, HEIGHT)
        # Return a provider that reflects what we have made
        data_resource = StreamResourceInfo(
            data_key=detector_name,
            shape=(HEIGHT, WIDTH),
            # NDAttributes appear to always be configured with
            # this chunk size
            chunk_shape=(1, HEIGHT, WIDTH),
            dtype_numpy=np.dtype(np.uint8).str,
            parameters={"dataset": DATA_PATH},
        )
        sum_resource = StreamResourceInfo(
            data_key=f"{detector_name}-sum",
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

    async def stop(self) -> None:
        self.pattern_generator.close_file()

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        # The main dataset is always hinted
        return [detector_name]
