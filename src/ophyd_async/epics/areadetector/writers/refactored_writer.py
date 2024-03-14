import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional, Sequence

# Grouped imports for clarity
from bluesky.protocols import Descriptor, StreamAsset
from event_model import StreamDatum, StreamResource, compose_stream_resource
from ophyd_async.core import (AsyncStatus, DEFAULT_TIMEOUT, DetectorWriter, Device,
                              DirectoryInfo, DirectoryProvider, NameProvider,
                              ShapeProvider, set_and_wait_for_value, wait_for_value)
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

# Simplifying inheritance by directly using Device class
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

class NDFileHDF(NDPluginBase):
    def __init__(self, prefix: str, name="") -> None:
        super().__init__(prefix, name)
        # Initializing signals more systematically
        signal_attributes = [
            ("position_mode", bool), ("compression", Compression),
            ("num_extra_dims", int), ("file_path", str), ("file_name", str),
            ("file_path_exists", bool, True), ("file_template", str),
            ("full_file_name", str, True), ("file_write_mode", FileWriteMode),
            ("num_capture", int), ("num_captured", int, True),
            ("swmr_mode", bool), ("lazy_open", bool), ("capture", bool),
            ("flush_now", bool), ("array_size0", int, True),
            ("array_size1", int, True)
        ]
        for attr_name, attr_type, is_read_only=False in signal_attributes:
            value = ad_r(attr_type, prefix + attr_name) if is_read_only else ad_rw(attr_type, prefix + attr_name)
            setattr(self, attr_name, value)

class HdfStreamProvider:
    def __init__(self, directory_info: DirectoryInfo, full_file_name: Path, datasets: List[HDFDataset]) -> None:
        self._last_emitted = 0
        self._bundles = self._compose_bundles(directory_info, full_file_name, datasets)

    def _compose_bundles(self, directory_info: DirectoryInfo, full_file_name: Path, datasets: List[HDFDataset]) -> List[StreamAsset]:
        path = str(full_file_name.relative_to(directory_info.root))
        root = str(directory_info.root)
        return [
            compose_stream_resource(spec="AD_HDF5_SWMR_SLICE", root=root, data_key=ds.name,
                                    resource_path=path, resource_kwargs={
                                        "path": ds.path, "multiplier": ds.multiplier,
                                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp"})
            for ds in datasets
        ]


class HDFWriter(DetectorWriter):
    def __init__(self, hdf: NDFileHDF, directory_provider: DirectoryProvider, name_provider: NameProvider, shape_provider: ShapeProvider, **scalar_datasets_paths: str) -> None:
        self.hdf = hdf
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._shape_provider = shape_provider
        self._scalar_datasets_paths = scalar_datasets_paths
        self._capture_status: Optional[AsyncStatus] = None
        self._datasets: List[HDFDataset] = []
        self._file: Optional[HdfStreamProvider] = None
        self._multiplier = 1

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        info = self._directory_provider()
        await self._setup_hdf_parameters(info, multiplier)
        self._initialize_datasets(multiplier)
        return self._compose_descriptors()

    async def _setup_hdf_parameters(self, info, multiplier):
        await asyncio.gather(
            self.hdf.setup_file_parameters(info.root / info.resource_dir, f"{info.prefix}{self.hdf.name}{info.suffix}", multiplier),
            self.hdf.set_stream_mode()
        )
        assert await self.hdf.file_path_exists.get_value(), f"File path {self.hdf.file_path.get_value()} for hdf plugin does not exist"

    def _initialize_datasets(self, multiplier):
        name = self._name_provider()
        detector_shape = tuple(await self._shape_provider())
        self._multiplier = multiplier
        self._datasets = [HDFDataset(name, "/entry/data/data", detector_shape, multiplier)] + [
            HDFDataset(f"{name}-{ds_name}", f"/entry/instrument/NDAttributes/{ds_path}", (), multiplier)
            for ds_name, ds_path in self._scalar_datasets_paths.items()
        ]

    def _compose_descriptors(self) -> Dict[str, Descriptor]:
        outer_shape = (self._multiplier,) if self._multiplier > 1 else ()
        return {
            ds.name: Descriptor(source=self.hdf.full_file_name.source, shape=outer_shape + tuple(ds.shape), dtype="array" if ds.shape else "number", external="STREAM:")
            for ds in self._datasets
        }

    async def observe_indices_written(self, timeout=DEFAULT_TIMEOUT) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self.hdf.num_captured, timeout):
            yield num_captured // self._multiplier

    async def get_indices_written(self) -> int:
        num_captured = await self.hdf.num_captured.get_value()
        return num_captured // self._multiplier

    async def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
        await self.hdf.flush_now.set(True)
        if indices_written and not self._file:
            path = Path(await self.hdf.full_file_name.get_value())
            self._file = HdfStreamProvider(self._directory_provider(), path, self._datasets)
            for doc in self._file.stream_resources():
                yield "stream_resource", doc
        for doc in self._file.stream_data(indices_written):
            yield "stream_datum", doc

    async def close(self):
        await self.hdf.stop_capture()
        if self._capture_status:
            await self._capture_status
