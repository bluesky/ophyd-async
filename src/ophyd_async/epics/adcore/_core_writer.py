

import asyncio
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Optional
from ophyd_async.core._detector import DetectorWriter
from ophyd_async.core._providers import NameProvider, PathProvider, DatasetDescriber
from ophyd_async.core._signal import observe_value, wait_for_value
from ophyd_async.core._status import AsyncStatus
from ophyd_async.core._utils import DEFAULT_TIMEOUT
from ._utils import FileWriteMode
from ._core_io import NDArrayBaseIO, NDFileIO
from event_model import DataKey


class ADWriter(DetectorWriter):
    def __init__(
        self,
        fileio: NDFileIO,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
        file_extension: str,
        mimetype: str,
        *plugins: NDArrayBaseIO,
    ) -> None:
        self.fileio = fileio
        self._path_provider = path_provider
        self._name_provider = name_provider
        self._dataset_describer = dataset_describer
        self._file_extension = file_extension
        self._mimetype = mimetype
        self._last_emitted = 0
        self._emitted_resource = False

        self._plugins = plugins
        self._capture_status: Optional[AsyncStatus] = None
        self._multiplier = 1

    async def collect_frame_info(self):
        detector_shape = tuple(await self._dataset_describer())
        self._multiplier = multiplier
        outer_shape = (multiplier,) if multiplier > 1 else ()
        frame_shape = detector_shape[:-1] if len(detector_shape) > 0 else []
        dtype_numpy = (
            convert_ad_dtype_to_np(detector_shape[-1])
            if len(detector_shape) > 0
            else ""
        )
        return outer_shape, frame_shape, dtype_numpy

    async def begin_capture(self) -> None:
        info = self._path_provider(device_name=self.fileio.name)

        # Set the directory creation depth first, since dir creation callback happens
        # when directory path PV is processed.
        await self.fileio.create_directory.set(info.create_dir_depth)

        await asyncio.gather(
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.fileio.file_path.set(str(info.directory_path)),
            self.fileio.file_name.set(info.filename),
            self.fileio.file_template.set("%s/%s" + self._file_extension),
            self.fileio.file_write_mode.set(FileWriteMode.stream),
            # Never use custom xml layout file but use the one defined
            # in the source code file NDFilefileio5LayoutXML.cpp
            self.fileio.xml_file_name.set(""),
        )

        assert (
            await self.fileio.file_path_exists.get_value()
        ), f"File path {info.directory_path} for hdf plugin does not exist"

        # Overwrite num_capture to go forever
        await self.fileio.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.fileio.capture, True)

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:

        self._emitted_resource = False
        self._last_emitted = 0
        outer_shape, frame_shape, dtype_numpy = self.collect_frame_info()

        name = self._name_provider()

        describe = {
            self._name_provider(): DataKey(
                source=self._name_provider(),
                shape=outer_shape + tuple(frame_shape),
                dtype="array",
                dtype_numpy=dtype_numpy,
                external="STREAM:",
            )
        }
        return describe

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(self.fileio.num_captured, timeout):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self.fileio.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        if indices_written:
            if not self._emitted_resource:
                file_path = Path(await self.fileio.file_path.get_value())
                filename_template = Path(await self.fileio.file_template.get_value())

                path_template = file_path / filename_template
                # stream resource says "here is a dataset",
                # stream datum says "here are N frames in that stream resource",
                # you get one stream resource and many stream datums per scan
                sres = {
                    "mimetype": self._mimetype,
                    "uri": path_template,
                    "data_key": self._name_provider(),
                    "uid": None,
                    "validate": True,
                }
                yield "stream_resource", sres

            if indices_written > self._last_emitted:
                doc = {
                    "indices" : {
                        "start": self._last_emitted,
                        "stop": indices_written,
                    }
                }
                self._last_emitted = indices_written
                yield "stream_datum", doc

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self.fileio.capture.set(False, wait=False)
        await wait_for_value(self.fileio.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
