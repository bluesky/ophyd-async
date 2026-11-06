import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorDataLogic,
    PathProvider,
    StreamableDataProvider,
    StreamResourceDataProvider,
    wait_for_value,
)

from ._io import XspressDetectorIO
from ._xsp_list_odin_io import XspressOdinListIO


class XspressOdinListDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        odin: XspressOdinListIO,
        driver: XspressDetectorIO,
    ):
        self.path_provider = path_provider
        self.odin = odin
        self.xsp = driver

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(datakey_name)
        # Setup the HDF writer
        filename = f"{path_info.filename}"
        await asyncio.gather(
            self.odin.file_path.set(str(path_info.directory_path)),
            self.odin.file_prefix.set(filename),
        )
        # Start writing
        await self.odin.fp.start_writing.trigger()
        await wait_for_value(self.odin.writing, True, timeout=DEFAULT_TIMEOUT)

        # Return a provider that reflects what we have made
        # I'll have to rewrite this so that we check data shape for every
        # dataset as they might be different from one another
        # Will need to regenerate each dataset with their specific datatypes
        # shapes should be consistent between all datasets though.
        # data_shape = await asyncio.gather(self.odin.fp.data_dims_0.get_value())
        # resource = StreamResourceInfo(
        #     data_key=datakey_name,
        #     shape=data_shape,
        #     chunk_shape=(1, *data_shape),
        #     dtype_numpy=np.dtype("uint32").str,
        #     parameters={"dataset": "/data"},
        # )
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{filename}",
            resources=[],
            mimetype="application/x-hdf5",
            collections_written_signal=self.xsp.frames_acquired,
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self.odin.fp.stop_writing.trigger(),
        )
