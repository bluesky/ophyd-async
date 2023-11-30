import asyncio
from typing import AsyncIterator, Dict, List, Optional

from bluesky.protocols import Asset, Descriptor, Hints

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorWriter,
    DirectoryProvider,
    NameProvider,
    set_and_wait_for_value,
    wait_for_value,
)

from .panda_hdf import _HDFDataset, _HDFFile, PandaHDF


class PandaHDFWriter(DetectorWriter):
    def __init__(
        self,
        hdf: PandaHDF,
        directory_provider: DirectoryProvider,
        name_provider: NameProvider,
        **scalar_datasets_paths: str,
    ) -> None:
        self.hdf = hdf
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._scalar_datasets_paths = scalar_datasets_paths
        self._capture_status: Optional[AsyncStatus] = None
        self._datasets: List[_HDFDataset] = []
        self._file: Optional[_HDFFile] = None
        self._multiplier = 1
        if self._multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, " "multiplier should be 1"
            )

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self._file = None
        info = self._directory_provider()
        await asyncio.gather(
            self.hdf.file_path.set(info.directory_path),
            self.hdf.file_name.set(f"{info.filename_prefix}.h5"),
        )

        # Overwrite num_capture to go forever
        await self.hdf.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.hdf.capture, True)
        name = self._name_provider()
        if multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, " "multiplier should be 1"
            )
        self._multiplier = multiplier
        self._datasets = []
        # Add all the scalar datasets
        for ds_name, ds_path in self._scalar_datasets_paths.items():
            self._datasets.append(
                _HDFDataset(
                    f"{name}-{ds_name}",
                    ds_path,
                    (),
                    multiplier,
                )
            )
        describe = {
            ds.name: Descriptor(
                source=self.hdf.full_file_name.source,
                shape=ds.shape,
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        def matcher(value: int) -> bool:
            return value // self._multiplier >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(self.hdf.num_written, matcher, timeout=timeout)

    async def get_indices_written(self) -> int:
        num_written = await self.hdf.num_written.get_value()
        return num_written // self._multiplier

    async def collect_stream_docs(self, indices_written: int) -> AsyncIterator[Asset]:
        # TODO: fail if we get dropped frames
        await self.hdf.flush_now.set(True)
        if indices_written:
            if not self._file:
                self._file = _HDFFile(
                    await self.hdf.full_file_name.get_value(), self._datasets
                )
                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(False, wait=False)
        await wait_for_value(self.hdf.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
