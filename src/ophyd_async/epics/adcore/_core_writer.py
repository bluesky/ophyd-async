import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Generic, TypeVar, get_args
from urllib.parse import urlunparse

from bluesky.protocols import Hints, StreamAsset
from event_model import (
    ComposeStreamResource,
    DataKey,
    StreamRange,
)

from ophyd_async.core._detector import DetectorWriter
from ophyd_async.core._providers import DatasetDescriber, NameProvider, PathProvider
from ophyd_async.core._signal import (
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.core._status import AsyncStatus
from ophyd_async.core._utils import DEFAULT_TIMEOUT

# from ophyd_async.epics.adcore._core_logic import ADBaseDatasetDescriber
from ._core_io import (
    ADBaseDatasetDescriber,
    Callback,
    NDArrayBaseIO,
    NDFileIO,
    NDPluginBaseIO,
)
from ._utils import FileWriteMode

NDFileIOT = TypeVar("NDFileIOT", bound=NDFileIO)
ADWriterT = TypeVar("ADWriterT", bound="ADWriter")


class ADWriter(DetectorWriter, Generic[NDFileIOT]):
    default_suffix: str = "FILE1:"

    def __init__(
        self,
        fileio: NDFileIOT,
        path_provider: PathProvider,
        name_provider: NameProvider,
        dataset_describer: DatasetDescriber,
        file_extension: str = "",
        mimetype: str = "",
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        self._plugins = plugins or {}
        self.fileio = fileio
        self._path_provider = path_provider
        self._name_provider = name_provider
        self._dataset_describer = dataset_describer
        self._file_extension = file_extension
        self._mimetype = mimetype
        self._last_emitted = 0
        self._emitted_resource = None

        self._capture_status: AsyncStatus | None = None
        self._multiplier = 1
        self._filename_template = "%s%s_%6.6d"

    @classmethod
    def with_io(
        cls: type[ADWriterT],
        prefix: str,
        path_provider: PathProvider,
        dataset_source: NDArrayBaseIO | None = None,
        fileio_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> ADWriterT:
        try:
            fileio_cls = get_args(cls.__orig_bases__[0])[0]  # type: ignore
        except IndexError as err:
            raise RuntimeError("File IO class for writer not specified!") from err

        fileio = fileio_cls(prefix + (fileio_suffix or cls.default_suffix))
        dataset_describer = ADBaseDatasetDescriber(dataset_source or fileio)

        def name_provider() -> str:
            if fileio.parent == "Not attached to a detector":
                raise RuntimeError("Initializing writer without parent detector!")
            return fileio.parent.name

        writer = cls(
            fileio, path_provider, name_provider, dataset_describer, plugins=plugins
        )
        return writer

    async def begin_capture(self) -> None:
        info = self._path_provider(device_name=self._name_provider())

        await self._fileio.enable_callbacks.set(Callback.ENABLE)

        # Set the directory creation depth first, since dir creation callback happens
        # when directory path PV is processed.
        await self._fileio.create_directory.set(info.create_dir_depth)

        await asyncio.gather(
            # See https://github.com/bluesky/ophyd-async/issues/122
            self._fileio.file_path.set(str(info.directory_path)),
            self._fileio.file_name.set(info.filename),
            self._fileio.file_write_mode.set(FileWriteMode.STREAM),
            # For non-HDF file writers, use AD file templating mechanism
            # for generating multi-image datasets
            self._fileio.file_template.set(
                self._filename_template + self._file_extension
            ),
            self._fileio.auto_increment.set(True),
            self._fileio.file_number.set(0),
        )

        assert (
            await self._fileio.file_path_exists.get_value()
        ), f"File path {info.directory_path} for file plugin does not exist!"

        # Overwrite num_capture to go forever
        await self._fileio.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(
            self._fileio.capture, True, wait_for_set_completion=False
        )

    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        self._emitted_resource = None
        self._last_emitted = 0
        self._multiplier = multiplier
        frame_shape = await self._dataset_describer.shape()
        dtype_numpy = await self._dataset_describer.np_datatype()

        await self.begin_capture()

        describe = {
            self._name_provider(): DataKey(
                source=self._name_provider(),
                shape=list(frame_shape),
                dtype="array",
                dtype_numpy=dtype_numpy,
                external="STREAM:",
            )  # type: ignore
        }
        return describe

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(self._fileio.num_captured, timeout):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self._fileio.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        if indices_written:
            if not self._emitted_resource:
                file_path = Path(await self._fileio.file_path.get_value())
                file_name = await self._fileio.file_name.get_value()
                file_template = file_name + "_{:06d}" + self._file_extension

                frame_shape = await self._dataset_describer.shape()

                uri = urlunparse(
                    (
                        "file",
                        "localhost",
                        str(file_path.absolute()) + "/",
                        "",
                        "",
                        None,
                    )
                )

                bundler_composer = ComposeStreamResource()

                self._emitted_resource = bundler_composer(
                    mimetype=self._mimetype,
                    uri=uri,
                    data_key=self._name_provider(),
                    parameters={
                        # Assume that we always write 1 frame per file/chunk
                        "chunk_shape": (1, *frame_shape),
                        # Include file template for reconstruction in consolidator
                        "template": file_template,
                    },
                    uid=None,
                    validate=True,
                )

                yield "stream_resource", self._emitted_resource.stream_resource_doc

            # Indices are relative to resource
            if indices_written > self._last_emitted:
                indices: StreamRange = {
                    "start": self._last_emitted,
                    "stop": indices_written,
                }
                self._last_emitted = indices_written
                yield (
                    "stream_datum",
                    self._emitted_resource.compose_stream_datum(indices),
                )

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self._fileio.capture.set(False, wait=False)
        await wait_for_value(self._fileio.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
