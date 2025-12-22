import asyncio

import numpy as np
from bluesky.protocols import Hints

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorDataLogic,
    PathProvider,
    SignalR,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    wait_for_value,
)

from ._io import OdinIO


class OdinDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        odin: OdinIO,
        detector_bit_depth: SignalR[int],
    ):
        self.path_provider = path_provider
        self.odin = odin
        self.detector_bit_depth = detector_bit_depth

    async def prepare_unbounded(self, device_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(device_name)
        # Get the current bit depth
        datatype = f"uint{await self.detector_bit_depth.get_value()}"
        # Setup the HDF writer
        await asyncio.gather(
            self.odin.fp.data_datatype.set(datatype),
            self.odin.fp.data_compression.set("BSLZ4"),
            self.odin.fp.frames.set(0),
            self.odin.fp.process_frames_per_block.set(1000),
            self.odin.fp.file_path.set(str(path_info.directory_path)),
            self.odin.mw.directory.set(str(path_info.directory_path)),
            self.odin.fp.file_prefix.set(path_info.filename),
            self.odin.mw.file_prefix.set(path_info.filename),
            self.odin.mw.acquisition_id.set(path_info.filename),
        )
        # Start writing
        await self.odin.fp.start_writing.trigger()
        await wait_for_value(self.odin.fp.writing, True, timeout=DEFAULT_TIMEOUT)
        # Return a provider that reflects what we have made
        data_shape = await asyncio.gather(
            self.odin.fp.data_dims_0.get_value(), self.odin.fp.data_dims_1.get_value()
        )
        resource = StreamResourceInfo(
            data_key=device_name,
            shape=data_shape,
            dtype_numpy=np.dtype(datatype).str,
            chunk_shape=(1, *data_shape),
            parameters={"dataset": "/data"},
        )
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{path_info.filename}.h5",
            resources=[resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.odin.fp.frames_written,
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self.odin.fp.stop_writing.trigger(),
            self.odin.mw.stop.trigger(),
        )

    def get_hints(self, device_name: str) -> Hints:
        # The main dataset is always hinted
        return {"fields": [device_name]}
