import asyncio
from collections.abc import Sequence

import numpy as np

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorDataLogic,
    PathProvider,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    wait_for_value,
)

from ._xsp_odin_io import XspressOdinIO


class XspressOdinDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        odin: XspressOdinIO,
    ):
        self.path_provider = path_provider
        self.odin = odin

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(datakey_name)
        # Setup the HDF writer
        filename = f"{path_info.filename}.h5"
        await asyncio.gather(
            self.odin.fp.data_datatype.set("uint32"),
            self.odin.fp.data_compression.set("BSLZ4"),
            self.odin.fp.frames.set(0),
            self.odin.fp.process_frames_per_block.set(1000),
            self.odin.file_path.set(str(path_info.directory_path)),
            self.odin.file_prefix.set(filename),
        )
        # Start writing
        await self.odin.fp.start_writing.trigger()
        await wait_for_value(self.odin.writing, True, timeout=DEFAULT_TIMEOUT)
        # Return a provider that reflects what we have made
        data_shape = await asyncio.gather(
            self.odin.fp.data_dims_0.get_value(), self.odin.fp.data_dims_1.get_value()
        )
        resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=data_shape,
            chunk_shape=(1, *data_shape),
            dtype_numpy=np.dtype("uint32").str,
            parameters={"dataset": "/data"},
        )
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{filename}",
            resources=[resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.odin.fp.frames_written,
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self.odin.fp.stop_writing.trigger(),
        )

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        # The main dataset is always hinted
        return [datakey_name]
