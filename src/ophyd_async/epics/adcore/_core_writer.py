import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import PureWindowsPath
from typing import Generic, TypeVar, get_args

from bluesky.protocols import Hints, StreamAsset
from event_model import (  # type: ignore
    ComposeStreamResource,
    DataKey,
    StreamRange,
)
from pydantic import PositiveInt

from ophyd_async.core._detector import DetectorWriter
from ophyd_async.core._providers import DatasetDescriber, PathInfo, PathProvider
from ophyd_async.core._signal import (
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.core._status import AsyncStatus
from ophyd_async.core._utils import DEFAULT_TIMEOUT, error_if_none

# from ophyd_async.epics.adcore._core_logic import ADBaseDatasetDescriber
from ._core_io import (
    ADBaseDatasetDescriber,
    ADCallbacks,
    NDArrayBaseIO,
    NDFileIO,
    NDFilePluginIO,
    NDPluginBaseIO,
)
from ._utils import ADFileWriteMode

NDFileIOT = TypeVar("NDFileIOT", bound=NDFileIO)
ADWriterT = TypeVar("ADWriterT", bound="ADWriter")


class ADWriter(DetectorWriter, Generic[NDFileIOT]):
    """Common behavior for all areaDetector writers."""

    default_suffix: str = "FILE1:"

    def __init__(
        self,
        fileio: NDFileIOT,
        path_provider: PathProvider,
        dataset_describer: DatasetDescriber,
        file_extension: str = "",
        mimetype: str = "",
        plugins: dict[str, NDPluginBaseIO] | None = None,
    ) -> None:
        self._plugins = plugins or {}
        self.fileio = fileio
        self._path_provider: PathProvider = path_provider
        self._path_info: PathInfo | None = None
        self._dataset_describer = dataset_describer
        self._file_extension = file_extension
        self._mimetype = mimetype
        self._last_emitted = 0
        self._emitted_resource = None

        self._capture_status: AsyncStatus | None = None
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

        writer = cls(fileio, path_provider, dataset_describer, plugins=plugins)
        return writer

    async def _begin_capture(self, name: str) -> None:
        path_info = error_if_none(
            self._path_info, "Writer must be opened before beginning capture!"
        )

        if isinstance(self.fileio, NDFilePluginIO):
            await self.fileio.enable_callbacks.set(ADCallbacks.ENABLE)

        # Set the directory creation depth first, since dir creation callback happens
        # when directory path PV is processed.
        await self.fileio.create_directory.set(path_info.create_dir_depth)

        # Need to ensure that trailing separator is added to the directory path.
        # When setting the path for windows based AD IOCs, a '/' is added rather than
        # a '\\', which will cause the readback to never register the same value.
        dir_path_as_str = str(path_info.directory_path)
        separator = "/"
        if isinstance(path_info.directory_path, PureWindowsPath):
            separator = "\\"

        dir_path_as_str += separator

        await asyncio.gather(
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.fileio.file_path.set(dir_path_as_str),
            self.fileio.file_name.set(path_info.filename),
            self.fileio.file_write_mode.set(ADFileWriteMode.STREAM),
            # For non-HDF file writers, use AD file templating mechanism
            # for generating multi-image datasets
            self.fileio.file_template.set(
                self._filename_template + self._file_extension
            ),
            self.fileio.auto_increment.set(True),
            self.fileio.file_number.set(0),
        )

        if not await self.fileio.file_path_exists.get_value():
            msg = f"Path {dir_path_as_str} doesn't exist or not writable!"
            raise FileNotFoundError(msg)

        # Overwrite num_capture to go forever
        await self.fileio.num_capture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(
            self.fileio.capture, True, wait_for_set_completion=False
        )

    async def open(
        self, name: str, exposures_per_event: PositiveInt = 1
    ) -> dict[str, DataKey]:
        self._emitted_resource = None
        self._last_emitted = 0
        self._exposures_per_event = exposures_per_event
        frame_shape = await self._dataset_describer.shape()
        dtype_numpy = await self._dataset_describer.np_datatype()

        self._path_info = self._path_provider(device_name=name)

        await self._begin_capture(name)

        describe = {
            name: DataKey(
                source=self.fileio.full_file_name.source,
                shape=[exposures_per_event, *frame_shape],
                dtype="array",
                dtype_numpy=dtype_numpy,
                external="STREAM:",
            )  # type: ignore
        }
        return describe

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected."""
        async for num_captured in observe_value(self.fileio.num_captured, timeout):
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        num_captured = await self.fileio.num_captured.get_value()
        return num_captured // self._exposures_per_event

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        path_info = error_if_none(
            self._path_info, "Writer must be opened before collecting stream docs!"
        )

        if indices_written:
            if not self._emitted_resource:
                file_name = await self.fileio.file_name.get_value()
                file_template = file_name + "_{:06d}" + self._file_extension

                frame_shape = await self._dataset_describer.shape()

                bundler_composer = ComposeStreamResource()

                self._emitted_resource = bundler_composer(
                    mimetype=self._mimetype,
                    uri=str(path_info.directory_uri),
                    # TODO no reference to detector's name
                    data_key=name,
                    parameters={
                        # Assume that we always write 1 frame per file/chunk, this
                        # may change to self._exposures_per_event in the future
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
        await self.fileio.capture.set(False, wait=False)
        await wait_for_value(self.fileio.capture, False, DEFAULT_TIMEOUT)
        if self._capture_status and not self._capture_status.done:
            # We kicked off an open, so wait for it to return
            await self._capture_status
        self._capture_status = None

    def get_hints(self, name: str) -> Hints:
        return {"fields": [name]}
