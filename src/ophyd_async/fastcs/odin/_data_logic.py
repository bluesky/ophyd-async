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

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> StreamableDataProvider:
        # Odin sizes its own chunks and writes for as long as it is told to, so
        # neither the frame period nor the count is used here yet.
        del period, num_collections
        # Unlike other data logics this one cannot describe its data without
        # starting: the frame shape is only readable from the file processor
        # once it is writing. So it does its own writes here and has nothing
        # left for start(). That is safe while it is the only kind of provider a
        # detector carrying it can produce, since it is then never discarded.
        # Work out where to write
        path_info = self.path_provider(datakey_name)
        # Get the current bit depth
        datatype = f"uint{await self.detector_bit_depth.get_value()}"
        # Setup the HDF writer
        filename = f"{path_info.filename}"
        await self.odin.acquisition_id.set("")
        await asyncio.gather(
            self.odin.file_prefix.set(filename),
            self.odin.file_path.set(str(path_info.directory_path)),
            self.odin.fp.data_compression.set("BSLZ4"),
            self.odin.fp.data_datatype.set(datatype),
            self.odin.fp.frames.set(0),
            self.odin.block_size.set(
                100000  # Needed temporarily, see https://github.com/bluesky/ophyd-async/issues/1272
            ),
        )
        # Start writing
        await self.odin.fp.start_writing.trigger()
        await wait_for_value(self.odin.writing, True, timeout=DEFAULT_TIMEOUT)
        # Must ensure frames_written reset
        # See issue: https://github.com/DiamondLightSource/fastcs-odin/issues/107
        await wait_for_value(self.odin.fp.frames_written, 0, timeout=DEFAULT_TIMEOUT)
        # Return a provider that reflects what we have made
        data_shape = await asyncio.gather(
            self.odin.fp.data_dims_0.get_value(), self.odin.fp.data_dims_1.get_value()
        )
        resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=data_shape,
            chunk_shape=(1, *data_shape),
            dtype_numpy=np.dtype(datatype).str,
            parameters={"dataset": "/data"},
        )
        return StreamResourceDataProvider(
            # Should be _vds instead of _000001, see https://github.com/bluesky/ophyd-async/issues/1272
            uri=f"{path_info.directory_uri}{filename}_000001.h5",
            resources=[resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.odin.fp.frames_written,
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self.odin.fp.stop_writing.trigger(),
            self.odin.mw.stop_.trigger(),
        )

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        # The main dataset is always hinted
        return [datakey_name]
