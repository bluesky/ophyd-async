import asyncio

import numpy as np

from ophyd_async.core import (
    DetectorDataLogic,
    PathProvider,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
)

from ._block import DataBlock, PandaCaptureMode


class PandaHDFDataLogic(DetectorDataLogic):
    def __init__(
        self,
        path_provider: PathProvider,
        data_block: DataBlock,
    ):
        self.path_provider = path_provider
        self.data_block = data_block

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        # Work out where to write
        path_info = self.path_provider(detector_name)
        # Set create dir depth first to guarantee that callback when setting
        # directory path has correct value
        await self.data_block.create_directory.set(path_info.create_dir_depth)
        # Setup the HDF writer
        await asyncio.gather(
            self.data_block.flush_period.set(0),
            self.data_block.hdf_directory.set(str(path_info.directory_path)),
            self.data_block.hdf_file_name.set(
                f"{path_info.filename}.h5",
            ),
            self.data_block.capture_mode.set(PandaCaptureMode.FOREVER),
        )
        # Make sure that directory exists or has been created.
        if not await self.data_block.directory_exists.get_value() == 1:
            raise OSError(
                f"Directory {path_info.directory_path} does not exist or "
                "is not writable by the PandABlocks-ioc!"
            )
        # Start capturing
        await self.data_block.capture.set(True)
        # Load data from the datasets PV on the panda, update internal
        # representation of datasets that the panda will write.
        capture_table = await self.data_block.datasets.get_value()
        resources = [
            StreamResourceInfo(
                data_key=dataset_name,
                shape=(),
                dtype_numpy=np.dtype(np.float64).str,
                # TODO: Update chunk size to read signal once available in IOC
                # Currently PandA IOC sets chunk size to 1024 points per chunk
                chunk_shape=(1024,),
                parameters={"dataset": f"/{dataset_name}"},
            )
            for dataset_name in capture_table.name
        ]
        return StreamResourceDataProvider(
            uri=f"{path_info.directory_uri}{path_info.filename}.h5",
            resources=resources,
            mimetype="application/x-hdf5",
            collections_written_signal=self.data_block.num_captured,
        )

    async def stop(self) -> None:
        await self.data_block.capture.set(False)
