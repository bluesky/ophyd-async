import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    HDFDatasetDescription,
    HDFDocumentComposer,
    PathProvider,
    observe_value,
    wait_for_value,
)

from ._block import DataBlock, PandaCaptureMode


class PandaHDFWriter(DetectorWriter):
    """For writing for PandA data from the `DataBlock`."""

    def __init__(
        self,
        path_provider: PathProvider,
        panda_data_block: DataBlock,
    ) -> None:
        self.panda_data_block = panda_data_block
        self._path_provider = path_provider
        self._datasets: list[HDFDatasetDescription] = []
        self._composer: HDFDocumentComposer | None = None

    # Triggered on PCAP arm
    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        self._composer = None
        """Retrieve and get descriptor of all PandA signals marked for capture."""
        self._exposures_per_event = exposures_per_event
        # Ensure flushes are immediate
        await self.panda_data_block.flush_period.set(0)

        info = self._path_provider(device_name=name)

        # Set create dir depth first to guarantee that callback when setting
        # directory path has correct value
        await self.panda_data_block.create_directory.set(info.create_dir_depth)

        # Set the initial values
        await asyncio.gather(
            self.panda_data_block.hdf_directory.set(str(info.directory_path)),
            self.panda_data_block.hdf_file_name.set(
                f"{info.filename}.h5",
            ),
            self.panda_data_block.capture_mode.set(PandaCaptureMode.FOREVER),
        )

        # Make sure that directory exists or has been created.
        if not await self.panda_data_block.directory_exists.get_value() == 1:
            raise OSError(
                f"Directory {info.directory_path} does not exist or "
                "is not writable by the PandABlocks-ioc!"
            )

        # Wait for it to start, stashing the status that tells us when it finishes
        await self.panda_data_block.capture.set(True)

        describe = await self._describe(name)

        self._composer = HDFDocumentComposer(
            f"{info.directory_uri}{info.filename}.h5",
            self._datasets,
        )

        return describe

    async def _describe(self, name: str) -> dict[str, DataKey]:
        """Return a describe based on the datasets PV."""
        await self._update_datasets(name)
        describe = {
            ds.data_key: DataKey(
                source=self.panda_data_block.hdf_directory.source,
                shape=list(ds.shape),
                dtype="array"
                if self._exposures_per_event > 1 or len(ds.shape) > 1
                else "number",
                # PandA data should always be written as Float64
                dtype_numpy=ds.dtype_numpy,
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def _update_datasets(self, name: str) -> None:
        # Load data from the datasets PV on the panda, update internal
        # representation of datasets that the panda will write.
        capture_table = await self.panda_data_block.datasets.get_value()
        self._datasets = [
            # TODO: Update chunk size to read signal once available in IOC
            # Currently PandA IOC sets chunk size to 1024 points per chunk
            HDFDatasetDescription(
                data_key=dataset_name,
                dataset="/" + dataset_name,
                shape=(self._exposures_per_event,)
                if self._exposures_per_event > 1
                else (),
                dtype_numpy="<f8",
                chunk_shape=(1024,),
            )
            for dataset_name in capture_table.name
        ]

        # Warn user if dataset table is empty in PandA
        # i.e. no stream resources will be generated
        if len(self._datasets) == 0:
            self.panda_data_block.log.warning(
                f"PandA {name} DATASETS table is empty! "
                "No stream resource docs will be generated. "
                "Make sure captured positions have their corresponding "
                "*:DATASET PV set to a scientifically relevant name."
            )

    # Next few functions are exactly the same as AD writer. Could move as default
    # StandardDetector behavior
    async def wait_for_index(self, index: int, timeout: float | None = DEFAULT_TIMEOUT):
        def matcher(value: int) -> bool:
            # Index is already divided by exposures_per_event, so we need to also
            # divide the value by exposures_per_event to get the correct index
            return value // self._exposures_per_event >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(
            self.panda_data_block.num_captured, matcher, timeout=timeout
        )

    async def get_indices_written(self) -> int:
        return (
            await self.panda_data_block.num_captured.get_value()
            // self._exposures_per_event
        )

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected."""
        async for num_captured in observe_value(
            self.panda_data_block.num_captured, timeout
        ):
            yield num_captured // self._exposures_per_event

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if self._composer is None:
            msg = f"open() not called on {self}"
            raise RuntimeError(msg)
        for doc in self._composer.make_stream_docs(indices_written):
            yield doc

    # Could put this function as default for StandardDetector
    async def close(self):
        await self.panda_data_block.capture.set(
            False, wait=True, timeout=DEFAULT_TIMEOUT
        )
