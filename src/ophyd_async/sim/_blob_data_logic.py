import numpy as np
from bluesky.protocols import Hints

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

    async def prepare_unbounded(self, device_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(device_name)
        # Open the file
        write_path = path_info.directory_path / f"{path_info.filename}.h5"
        self.pattern_generator.open_file(write_path, WIDTH, HEIGHT)
        # Return a provider that reflects what we have made
        data_resource = StreamResourceInfo(
            data_key=device_name,
            shape=(HEIGHT, WIDTH),
            dtype_numpy=np.dtype(np.uint8).str,
            # NDAttributes appear to always be configured with
            # this chunk size
            chunk_shape=(1, HEIGHT, WIDTH),
            parameters={"dataset": DATA_PATH},
        )
        sum_resource = StreamResourceInfo(
            data_key=f"{device_name}-sum",
            shape=(),
            dtype_numpy=np.dtype(np.int64).str,
            # NDAttributes appear to always be configured with
            # this chunk size
            chunk_shape=(1024,),
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

    def get_hints(self, device_name: str) -> Hints:
        # The main dataset is always hinted
        return {"fields": [device_name]}
