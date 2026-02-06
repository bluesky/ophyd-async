import asyncio
from collections.abc import Sequence

import numpy as np

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

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(detector_name)
        # Get the current bit depth
        datatype = f"uint{await self.detector_bit_depth.get_value()}"
        # Setup the HDF writer
        filename = f"{path_info.filename}.h5"
        await asyncio.gather(
            self.odin.fp.data_datatype.set(datatype),
            self.odin.fp.data_compression.set("BSLZ4"),
            self.odin.fp.frames.set(0),
            self.odin.fp.process_frames_per_block.set(1000),
            self.odin.fp.file_path.set(str(path_info.directory_path)),
            self.odin.mw.directory.set(str(path_info.directory_path)),
            self.odin.fp.file_prefix.set(filename),
            self.odin.mw.file_prefix.set(filename),
            self.odin.mw.acquisition_id.set(filename),
        )
        # Start writing
        await self.odin.fp.start_writing.trigger()
        await wait_for_value(self.odin.fp.writing, True, timeout=DEFAULT_TIMEOUT)
        await wait_for_value(self.odin.mw.writing, True, timeout=DEFAULT_TIMEOUT)
        # Return a provider that reflects what we have made
        data_shape = await asyncio.gather(
            self.odin.fp.data_dims_0.get_value(), self.odin.fp.data_dims_1.get_value()
        )
        resource = StreamResourceInfo(
            data_key=detector_name,
            shape=data_shape,
            chunk_shape=(1, *data_shape),
            dtype_numpy=np.dtype(datatype).str,
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
            self.odin.mw.stop.trigger(),
        )

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        # The main dataset is always hinted
        return [detector_name]
