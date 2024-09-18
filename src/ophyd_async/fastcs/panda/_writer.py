import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

from bluesky.protocols import StreamAsset
from event_model import DataKey
from p4p.client.thread import Context

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    HDFDataset,
    HDFFile,
    NameProvider,
    PathProvider,
    observe_value,
    wait_for_value,
)

from ._block import DataBlock


class PandaHDFWriter(DetectorWriter):
    _ctxt: Context | None = None

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name_provider: NameProvider,
        panda_data_block: DataBlock,
    ) -> None:
        self.panda_data_block = panda_data_block
        self._prefix = prefix
        self._path_provider = path_provider
        self._name_provider = name_provider
        self._datasets: list[HDFDataset] = []
        self._file: HDFFile | None = None
        self._multiplier = 1

    # Triggered on PCAP arm
    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        """Retrieve and get descriptor of all PandA signals marked for capture"""

        # Ensure flushes are immediate
        await self.panda_data_block.flush_period.set(0)

        self._file = None
        info = self._path_provider(device_name=self._name_provider())

        # Set create dir depth first to guarantee that callback when setting
        # directory path has correct value
        await self.panda_data_block.create_directory.set(info.create_dir_depth)

        # Set the initial values
        await asyncio.gather(
            self.panda_data_block.hdf_directory.set(str(info.directory_path)),
            self.panda_data_block.hdf_file_name.set(
                f"{info.filename}.h5",
            ),
            self.panda_data_block.num_capture.set(0),
        )

        # Make sure that directory exists or has been created.
        if not await self.panda_data_block.directory_exists.get_value() == 1:
            raise OSError(
                f"Directory {info.directory_path} does not exist or "
                "is not writable by the PandABlocks-ioc!"
            )

        # Wait for it to start, stashing the status that tells us when it finishes
        await self.panda_data_block.capture.set(True)
        if multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, multiplier should be 1"
            )

        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        """
        Return a describe based on the datasets PV
        """

        await self._update_datasets()
        describe = {
            ds.data_key: DataKey(
                source=self.panda_data_block.hdf_directory.source,
                shape=list(ds.shape),
                dtype="array" if ds.shape != [1] else "number",
                # PandA data should always be written as Float64
                # Ignore type check until https://github.com/bluesky/event-model/issues/308
                dtype_numpy="<f8",  # type: ignore
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def _update_datasets(self) -> None:
        """
        Load data from the datasets PV on the panda, update internal
        representation of datasets that the panda will write.
        """

        capture_table = await self.panda_data_block.datasets.get_value()
        self._datasets = [
            # TODO: Update chunk size to read signal once available in IOC
            # Currently PandA IOC sets chunk size to 1024 points per chunk
            HDFDataset(
                dataset_name, "/" + dataset_name, [1], multiplier=1, chunk_shape=(1024,)
            )
            for dataset_name in capture_table["name"]
        ]

        # Warn user if dataset table is empty in PandA
        # i.e. no stream resources will be generated
        if len(self._datasets) == 0:
            self.panda_data_block.log.warning(
                f"PandA {self._name_provider()} DATASETS table is empty! "
                "No stream resource docs will be generated. "
                "Make sure captured positions have their corresponding "
                "*:DATASET PV set to a scientifically relevant name."
            )

    # Next few functions are exactly the same as AD writer. Could move as default
    # StandardDetector behavior
    async def wait_for_index(self, index: int, timeout: float | None = DEFAULT_TIMEOUT):
        def matcher(value: int) -> bool:
            return value >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(
            self.panda_data_block.num_captured, matcher, timeout=timeout
        )

    async def get_indices_written(self) -> int:
        return await self.panda_data_block.num_captured.get_value()

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(
            self.panda_data_block.num_captured, timeout
        ):
            yield num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if indices_written:
            if not self._file:
                self._file = HDFFile(
                    Path(await self.panda_data_block.hdf_directory.get_value())
                    / Path(await self.panda_data_block.hdf_file_name.get_value()),
                    self._datasets,
                )
                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    # Could put this function as default for StandardDetector
    async def close(self):
        await self.panda_data_block.capture.set(
            False, wait=True, timeout=DEFAULT_TIMEOUT
        )
