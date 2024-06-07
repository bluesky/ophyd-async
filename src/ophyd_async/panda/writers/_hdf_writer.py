import asyncio
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional

from bluesky.protocols import DataKey, StreamAsset
from p4p.client.thread import Context

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    DirectoryProvider,
    wait_for_value,
)
from ophyd_async.core.signal import observe_value

from .._common_blocks import CommonPandaBlocks
from ._panda_hdf_file import _HDFDataset, _HDFFile


class PandaHDFWriter(DetectorWriter):
    _ctxt: Optional[Context] = None

    def __init__(
        self,
        directory_provider: DirectoryProvider,
        panda_device: CommonPandaBlocks,
    ) -> None:
        self.panda_device = panda_device
        self._directory_provider = directory_provider
        self._datasets: List[_HDFDataset] = []
        self._file: Optional[_HDFFile] = None
        self._multiplier = 1

    # Triggered on PCAP arm
    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        """Retrieve and get descriptor of all PandA signals marked for capture"""

        # Ensure flushes are immediate
        await self.panda_device.data.flush_period.set(0)

        self._file = None
        info = self._directory_provider()
        # Set the initial values
        await asyncio.gather(
            self.panda_device.data.hdf_directory.set(
                str(info.root / info.resource_dir)
            ),
            self.panda_device.data.hdf_file_name.set(
                f"{info.prefix}{self.panda_device.name}{info.suffix}.h5",
            ),
            self.panda_device.data.num_capture.set(0),
        )

        # Wait for it to start, stashing the status that tells us when it finishes
        await self.panda_device.data.capture.set(True)
        if multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, multiplier should be 1"
            )

        return await self._describe()

    async def _describe(self) -> Dict[str, DataKey]:
        """
        Return a describe based on the datasets PV
        """

        await self._update_datasets()
        describe = {
            ds.data_key: DataKey(
                source=self.panda_device.data.hdf_directory.source,
                shape=ds.shape,
                dtype="array" if ds.shape != [1] else "number",
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

        capture_table = await self.panda_device.data.datasets.get_value()
        self._datasets = [
            _HDFDataset(dataset_name, dataset_name, [1], multiplier=1)
            for dataset_name in capture_table["name"]
        ]

    # Next few functions are exactly the same as AD writer. Could move as default
    # StandardDetector behavior
    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        def matcher(value: int) -> bool:
            return value >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(
            self.panda_device.data.num_captured, matcher, timeout=timeout
        )

    async def get_indices_written(self) -> int:
        return await self.panda_device.data.num_captured.get_value()

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(
            self.panda_device.data.num_captured, timeout
        ):
            yield num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if indices_written:
            if not self._file:
                self._file = _HDFFile(
                    self._directory_provider(),
                    Path(await self.panda_device.data.hdf_file_name.get_value()),
                    self._datasets,
                )
                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    # Could put this function as default for StandardDetector
    async def close(self):
        await self.panda_device.data.capture.set(
            False, wait=True, timeout=DEFAULT_TIMEOUT
        )
