import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Dict, Iterator, List, Optional, Sequence

# Grouped imports for clarity
from bluesky.protocols import Descriptor, StreamAsset
from event_model import StreamDatum, StreamResource, compose_stream_resource
from ophyd_async.core import (
    AsyncStatus,
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    DirectoryInfo,
    DirectoryProvider,
    NameProvider,
    ShapeProvider,
)
from ophyd_async.core.signal import observe_value
from ophyd_async.epics.signal import epics_signal_rw
from ..utils import FileWriteMode, ad_r, ad_rw


@dataclass
class HDFDataset:
    name: str
    path: str
    shape: Sequence[int]
    multiplier: int


class Compression(Enum):
    NONE = "None"
    NBIT = "N-bit"
    SZIP = "szip"
    ZLIB = "zlib"
    BLOSC = "Blosc"
    BSLZ4 = "BSLZ4"
    LZ4 = "LZ4"
    JPEG = "JPEG"


class Callback(Enum):
    ENABLE = "Enable"
    DISABLE = "Disable"


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        super().__init__(name)
        self.unique_id = ad_r(int, prefix + "UniqueId")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        super().__init__(prefix, name)
        self.nd_array_port = ad_rw(str, prefix + "NDArrayPort")
        self.enable_callback = ad_rw(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = ad_rw(int, prefix + "NDArrayAddress")


class HDFDataPointer(NDPluginBase):
    def __init__(self, prefix: str, name="") -> None:
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
    def __init__(
        self,
        directory_info: DirectoryInfo,
        full_file_name: Path,
        datasets: List[HDFDataset],
    ) -> None:
        self._last_emitted = 0
        self._bundles = self._compose_bundles(directory_info, full_file_name, datasets)

    def _compose_bundles(
        self,
        directory_info: DirectoryInfo,
        full_file_name: Path,
        datasets: List[HDFDataset],
    ) -> List[StreamAsset]:
        path = str(full_file_name.relative_to(directory_info.root))
        root = str(directory_info.root)
        return [
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
        data_pointer: HDFDataPointer,
        directory_provider: DirectoryProvider,
        name_provider: NameProvider,
        shape_provider: ShapeProvider,
        **scalar_datasets_paths: str,
    ) -> None:
        self.data_pointer = data_pointer
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._shape_provider = shape_provider
        self._scalar_datasets_paths = scalar_datasets_paths
        self._capture_status: Optional[AsyncStatus] = None
        self._datasets: List[HDFDataset] = []
        self._hdf_stream_provider: Optional[HdfStreamProvider] = None
        self._multiplier = 1

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        info = self._directory_provider()
        await self._setup_hdf_parameters(info, multiplier)
        self._initialize_datasets(multiplier)
        return self._compose_descriptors()

    async def _setup_hdf_parameters(self, info, multiplier):
        await asyncio.gather(
            self.data_pointer.setup_file_parameters(
                info.root / info.resource_dir,
                f"{info.prefix}{self.data_pointer.name}{info.suffix}",
                multiplier,
            ),
            self.data_pointer.set_stream_mode(),
        )
        assert (
            await self.data_pointer.file_path_exists.get_value()
        ), f"File path {self.data_pointer.file_path.get_value()} for hdf plugin does not exist"

    async def _initialize_datasets(self, multiplier) -> None:
        name = self._name_provider()
        detector_shape = tuple(await self._shape_provider())
        self._multiplier = multiplier
        self._datasets = [
            HDFDataset(name, "/entry/data/data", detector_shape, multiplier)
        ] + [
            HDFDataset(
                f"{name}-{ds_name}",
                f"/entry/instrument/NDAttributes/{ds_path}",
                (),
                multiplier,
            )
            for ds_name, ds_path in self._scalar_datasets_paths.items()
        ]

    def _compose_descriptors(self) -> Dict[str, Descriptor]:
        outer_shape = (self._multiplier,) if self._multiplier > 1 else ()
        return {
            ds.name: Descriptor(
                source=self.data_pointer.full_file_name.source,
                shape=outer_shape + tuple(ds.shape),
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(
            self.data_pointer.num_captured, timeout
        ):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self.data_pointer.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        await self.data_pointer.flush_now.set(True)
        if indices_written and not self._hdf_stream_provider:
            path = Path(await self.data_pointer.full_file_name.get_value())
            self._hdf_stream_provider = HdfStreamProvider(
                self._directory_provider(), path, self._datasets
            )
            for doc in self._hdf_stream_provider.stream_resources():
                yield "stream_resource", doc
        for doc in self._hdf_stream_provider.stream_data(indices_written):
            yield "stream_datum", doc

    async def close(self):
        await self.data_pointer.stop_capture()
        if self._capture_status:
            await self._capture_status
