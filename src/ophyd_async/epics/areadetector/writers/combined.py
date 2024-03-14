import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import (
    AsyncGenerator,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
)

from bluesky.protocols import Descriptor, StreamAsset
from event_model import StreamDatum, StreamResource, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorWriter,
    Device,
    DirectoryInfo,
    DirectoryProvider,
    NameProvider,
    ShapeProvider,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.core.signal import observe_value
from ophyd_async.epics.signal import epics_signal_rw

from ..utils import FileWriteMode, ad_r, ad_rw


@dataclass
class _HDFDataset:
    name: str
    path: str
    shape: Sequence[int]
    multiplier: int


class Compression(str, Enum):
    none = "None"
    nbit = "N-bit"
    szip = "szip"
    zlib = "zlib"
    blosc = "Blosc"
    bslz4 = "BSLZ4"
    lz4 = "LZ4"
    jpeg = "JPEG"


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = ad_r(int, prefix + "UniqueId")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        super().__init__(name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = ad_rw(str, prefix + "NDArrayPort")
        # todo why no boolean flag?
        self.enable_callback = ad_rw(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = ad_rw(int, prefix + "NDArrayAddress")
        super().__init__(prefix, name)


class NDFileHDF(NDPluginBase):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.position_mode = ad_rw(bool, prefix + "PositionMode")
        self.compression = ad_rw(Compression, prefix + "Compression")
        self.num_extra_dims = ad_rw(int, prefix + "NumExtraDims")
        self.file_path = ad_rw(str, prefix + "FilePath")
        self.file_name = ad_rw(str, prefix + "FileName")
        self.file_path_exists = ad_r(bool, prefix + "FilePathExists")
        self.file_template = ad_rw(str, prefix + "FileTemplate")
        self.full_file_name = ad_r(str, prefix + "FullFileName")
        self.file_write_mode = ad_rw(FileWriteMode, prefix + "FileWriteMode")
        self.num_capture = ad_rw(int, prefix + "NumCapture")
        self.num_captured = ad_r(int, prefix + "NumCaptured")
        self.swmr_mode = ad_rw(bool, prefix + "SWMRMode")
        self.lazy_open = ad_rw(bool, prefix + "LazyOpen")
        self.capture = ad_rw(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.array_size0 = ad_r(int, prefix + "ArraySize0")
        self.array_size1 = ad_r(int, prefix + "ArraySize1")
        super().__init__(prefix, name)


class HdfStreamProvider:
    """
    :param directory_info: Contains information about how to construct a StreamResource
    :param full_file_name: Absolute path to the file to be written
    :param datasets: Datasets to write into the file
    """

    def __init__(
        self,
        directory_info: DirectoryInfo,
        full_file_name: Path,
        datasets: List[_HDFDataset],
    ) -> None:
        self._last_emitted = 0
        path = str(full_file_name.relative_to(directory_info.root))
        root = str(directory_info.root)

        self._bundles = [
            compose_stream_resource(
                spec="AD_HDF5_SWMR_SLICE",
                root=root,
                data_key=ds.name,
                resource_path=path,
                resource_kwargs={
                    "path": ds.path,
                    "multiplier": ds.multiplier,
                    "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                },
            )
            for ds in datasets
        ]

    def stream_resources(self) -> Iterator[StreamResource]:
        for bundle in self._bundles:
            yield bundle.stream_resource_doc

    def stream_data(self, indices_written: int) -> Iterator[StreamDatum]:
        # Indices are relative to resource
        if indices_written > self._last_emitted:
            indices = dict(
                start=self._last_emitted,
                stop=indices_written,
            )
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield bundle.compose_stream_datum(indices)
        return None


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
        self._file: Optional[HdfStreamProvider] = None
        self._multiplier = 1

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self._file = None
        info = self._directory_provider()
        await asyncio.gather(
            self.hdf.num_extra_dims.set(0),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            # See https://github.com/bluesky/ophyd-async/issues/122
            self.hdf.file_path.set(str(info.root / info.resource_dir)),
            self.hdf.file_name.set(f"{info.prefix}{self.hdf.name}{info.suffix}"),
            self.hdf.file_template.set("%s/%s.h5"),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )

        assert (
            await self.hdf.file_path_exists.get_value()
        ), f"File path {self.hdf.file_path.get_value()} for hdf plugin does not exist"

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
            ds.name: Descriptor(
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
                self._file = HdfStreamProvider(
                    self._directory_provider(),
                    # See https://github.com/bluesky/ophyd-async/issues/122
                    path,
                    self._datasets,
                )
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
