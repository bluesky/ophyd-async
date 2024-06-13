import asyncio
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional

from bluesky.protocols import DataKey, Hints, StreamAsset

from ophyd_async.core import (DEFAULT_TIMEOUT, AsyncStatus, DetectorWriter,
                              DirectoryProvider, NameProvider, ShapeProvider,
                              observe_value, set_and_wait_for_value,
                              wait_for_value)

from ._hdfdataset import _HDFDataset
from ._hdffile import _HDFFile
from .nd_file_hdf import FileWriteMode, NDFileHDF


class HDFWriter(DetectorWriter):
    def __init__(
        self,
        hdf: NDFileHDF,
        directory_provider: DirectoryProvider,
        name_provider: NameProvider,
        shape_provider: ShapeProvider,
        **scalar_datasets_paths: str,
    ) -> None:
        self.hdf = hdf
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._shape_provider = shape_provider
        self._scalar_datasets_paths = scalar_datasets_paths
        self._capture_status: Optional[AsyncStatus] = None
        self._datasets: List[_HDFDataset] = []
        self._file: Optional[_HDFFile] = None
        self._multiplier = 1

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        self._file = None
        info = self._directory_provider()
        file_path = str(info.root / info.resource_dir)
        await asyncio.gather(
            self.hdf.num_extra_dims.set(0),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.hdf.file_path.set(file_path),
            self.hdf.file_name.set(f"{info.prefix}{self.hdf.name}{info.suffix}"),
            self.hdf.file_template.set("%s/%s.h5"),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
            # Never use custom xml layout file but use the one defined
            # in the source code file NDFileHDF5LayoutXML.cpp
            self.hdf.xml_file_name.set(""),
        )

        assert (
            await self.hdf.file_path_exists.get_value()
        ), f"File path {file_path} for hdf plugin does not exist"

        # Overwrite num_capture to go forever
        await self.hdf.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.hdf.capture, True)
        name = self._name_provider()
        detector_shape = tuple(await self._shape_provider())
        self._multiplier = multiplier
        outer_shape = (multiplier,) if multiplier > 1 else ()
        # Add the main data
        self._datasets = [
            _HDFDataset(name, "/entry/data/data", detector_shape, multiplier)
        ]
        # And all the scalar datasets
        for ds_name, ds_path in self._scalar_datasets_paths.items():
            self._datasets.append(
                _HDFDataset(
                    f"{name}-{ds_name}",
                    f"/entry/instrument/NDAttributes/{ds_path}",
                    (),
                    multiplier,
                )
            )
        describe = {
            ds.name: DataKey(
                source=self.hdf.full_file_name.source,
                shape=outer_shape + tuple(ds.shape),
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(self.hdf.num_captured, timeout):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self.hdf.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        await self.hdf.flush_now.set(True)
        if indices_written:
            if not self._file:
                path = Path(await self.hdf.full_file_name.get_value())
                self._file = _HDFFile(
                    self._directory_provider(),
                    # See https://github.com/bluesky/ophyd-async/issues/122
                    path,
                    self._datasets,
                )
                # stream resource says "here is a dataset",
                # stream datum says "here are N frames in that stream resource",
                # you get one stream resource and many stream datums per scan

                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        await wait_for_value(self.hdf.capture, 0, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
