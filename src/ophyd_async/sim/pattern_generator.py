from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Dict,
    List,
    Optional,
)

import h5py
import numpy as np
from bluesky.protocols import DataKey, StreamAsset

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.mock_signal_backend import MockSignalBackend
from ophyd_async.core.signal import SignalR, observe_value
from ophyd_async.core.utils import DEFAULT_TIMEOUT
from ophyd_async.epics.areadetector.writers.general_hdffile import _HDFDataset, _HDFFile

# raw data path
DATA_PATH = "_entry_data_data"

# pixel sum path
SUM_PATH = "_entry_sum"

MAX_UINT8_VALUE = np.iinfo(np.uint8).max

SLICE_NAME = "AD_HDF5_SWMR_SLICE"


@dataclass
class PatternDataset(_HDFDataset):
    dtype: Any
    maxshape: tuple[Any, ...]
    fillvalue: int = field(default_factory=int)


def get_full_file_description(
    datasets: List[PatternDataset], outer_shape: tuple[int, ...]
):
    full_file_description: Dict[str, DataKey] = {}
    for d in datasets:
        source = f"soft://{d.data_key}"
        shape = outer_shape + tuple(d.shape)
        dtype = "number" if d.shape == [1] else "array"
        descriptor = DataKey(
            source=source, shape=shape, dtype=dtype, external="STREAM:"
        )
        key = d.data_key
        full_file_description[key] = descriptor
    return full_file_description


def generate_gaussian_blob(height: int, width: int) -> np.ndarray:
    """Make a Gaussian Blob with float values in range 0..1"""
    x, y = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    d = np.sqrt(x * x + y * y)
    blob = np.exp(-(d**2))
    return blob


def generate_interesting_pattern(x: float, y: float) -> float:
    """This function is interesting in x and y in range -10..10, returning
    a float value in range 0..1
    """
    z = 0.5 + (np.sin(x) ** 10 + np.cos(10 + y * x) * np.cos(x)) / 2
    return z


class PatternGenerator:
    def __init__(
        self,
        saturation_exposure_time: float = 1,
        detector_width: int = 320,
        detector_height: int = 240,
    ) -> None:
        self.saturation_exposure_time = saturation_exposure_time
        self.exposure = saturation_exposure_time
        self.x = 0.0
        self.y = 0.0
        self.height = detector_height
        self.width = detector_width
        self.written_images_counter: int = 0

        # it automatically initializes to 0
        self.signal_backend = MockSignalBackend(int)
        self.mock_signal = SignalR(self.signal_backend)
        blob = np.array(
            generate_gaussian_blob(width=detector_width, height=detector_height)
            * MAX_UINT8_VALUE
        )
        self.STARTING_BLOB = blob
        self._hdf_stream_provider: Optional[_HDFFile] = None
        self._handle_for_h5_file: Optional[h5py.File] = None
        self.target_path: Optional[Path] = None

    async def write_image_to_file(self) -> None:
        assert self._handle_for_h5_file, "no file has been opened!"
        # prepare - resize the fixed hdf5 data structure
        # so that the new image can be written
        new_layer = self.written_images_counter + 1
        target_dimensions = (new_layer, self.height, self.width)

        # generate the simulated data
        intensity: float = generate_interesting_pattern(self.x, self.y)
        detector_data: np.uint8 = np.uint8(
            self.STARTING_BLOB
            * intensity
            * self.exposure
            / self.saturation_exposure_time
        )

        self._handle_for_h5_file[DATA_PATH].resize(target_dimensions)

        print(f"writing image {new_layer}")
        assert self._handle_for_h5_file, "no file has been opened!"
        self._handle_for_h5_file[DATA_PATH].resize(target_dimensions)

        self._handle_for_h5_file[SUM_PATH].resize((new_layer,))

        # write data to disc (intermediate step)
        self._handle_for_h5_file[DATA_PATH][self.written_images_counter] = detector_data
        self._handle_for_h5_file[SUM_PATH][self.written_images_counter] = np.sum(
            detector_data
        )

        # save metadata - so that it's discoverable
        self._handle_for_h5_file[DATA_PATH].flush()
        self._handle_for_h5_file[SUM_PATH].flush()

        # counter increment is last
        # as only at this point the new data is visible from the outside
        self.written_images_counter += 1
        await self.signal_backend.put(self.written_images_counter)

    def set_exposure(self, value: float) -> None:
        self.exposure = value

    def set_x(self, value: float) -> None:
        self.x = value

    def set_y(self, value: float) -> None:
        self.y = value

    async def open_file(
        self, directory: DirectoryProvider, multiplier: int = 1
    ) -> Dict[str, DataKey]:
        await self.mock_signal.connect()

        self.target_path = self._get_new_path(directory)

        self._handle_for_h5_file = h5py.File(self.target_path, "w", libver="latest")

        assert self._handle_for_h5_file, "not loaded the file right"

        datasets = self._get_datasets()
        for d in datasets:
            self._handle_for_h5_file.create_dataset(
                name=d.data_key,
                shape=d.shape,
                dtype=d.dtype,
                maxshape=d.maxshape,
            )

        # once datasets written, can switch the model to single writer multiple reader
        self._handle_for_h5_file.swmr_mode = True

        outer_shape = (multiplier,) if multiplier > 1 else ()
        full_file_description = get_full_file_description(datasets, outer_shape)

        # cache state to self
        self._datasets = datasets
        self.multiplier = multiplier
        self._directory_provider = directory
        return full_file_description

    def _get_new_path(self, directory: DirectoryProvider) -> Path:
        info = directory()
        filename = f"{info.prefix}pattern{info.suffix}.h5"
        new_path: Path = info.root / info.resource_dir / filename
        return new_path

    def _get_datasets(self) -> List[PatternDataset]:
        raw_dataset = PatternDataset(
            # name=data_name,
            data_key=DATA_PATH,
            dtype=np.uint8,
            shape=(1, self.height, self.width),
            maxshape=(None, self.height, self.width),
        )

        sum_dataset = _HDFDataset(
            data_key=SUM_PATH,
            dtype=np.float64,
            shape=(1,),
            maxshape=(None,),
            fillvalue=-1,
        )

        datasets: List[_HDFDataset] = [raw_dataset, sum_dataset]
        return datasets

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        """
        stream resource says "here is a dataset",
        stream datum says "here are N frames in that stream resource",
        you get one stream resource and many stream datums per scan
        """
        if self._handle_for_h5_file:
            self._handle_for_h5_file.flush()
        # when already something was written to the file
        if indices_written:
            # if no frames arrived yet, there's no file to speak of
            # cannot get the full filename the HDF writer will write
            # until the first frame comes in
            if not self._hdf_stream_provider:
                assert self.target_path, "open file has not been called"
                datasets = self._get_datasets()
                self._datasets = datasets
                self._hdf_stream_provider = _HDFFile(
                    self._directory_provider(),
                    self.target_path,
                    self._datasets,
                )
                for doc in self._hdf_stream_provider.stream_resources():
                    yield "stream_resource", doc
            if self._hdf_stream_provider:
                for doc in self._hdf_stream_provider.stream_data(indices_written):
                    yield "stream_datum", doc

    def close(self) -> None:
        if self._handle_for_h5_file:
            self._handle_for_h5_file.close()
            print("file closed")
            self._handle_for_h5_file = None

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self.mock_signal, timeout=timeout):
            yield num_captured // self.multiplier
