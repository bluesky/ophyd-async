from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path

import h5py
import numpy as np
from bluesky.protocols import StreamAsset
from event_model import DataKey

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    HDFDataset,
    HDFFile,
    PathProvider,
    observe_value,
    soft_signal_r_and_setter,
)

# raw data path
DATA_PATH = "/entry/data/data"

# pixel sum path
SUM_PATH = "/entry/sum"

MAX_UINT8_VALUE = np.iinfo(np.uint8).max


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
        saturation_exposure_time: float = 0.1,
        detector_width: int = 320,
        detector_height: int = 240,
    ) -> None:
        self.saturation_exposure_time = saturation_exposure_time
        self.exposure = saturation_exposure_time
        self.x = 0.0
        self.y = 0.0
        self.height = detector_height
        self.width = detector_width
        self.image_counter: int = 0

        # it automatically initializes to 0
        self.counter_signal, self._set_counter_signal = soft_signal_r_and_setter(int)
        self._full_intensity_blob = (
            generate_gaussian_blob(width=detector_width, height=detector_height)
            * MAX_UINT8_VALUE
        )
        self._hdf_stream_provider: HDFFile | None = None
        self._handle_for_h5_file: h5py.File | None = None
        self.target_path: Path | None = None

    def write_data_to_dataset(self, path: str, data_shape: tuple[int, ...], data):
        """Write data to named dataset, resizing to fit and flushing after."""
        assert self._handle_for_h5_file, "no file has been opened!"
        dset = self._handle_for_h5_file[path]
        assert isinstance(
            dset, h5py.Dataset
        ), f"Expected {path} to be dataset, got {dset}"
        dset.resize((self.image_counter + 1,) + data_shape)
        dset[self.image_counter] = data
        dset.flush()

    async def write_image_to_file(self) -> None:
        # generate the simulated data
        intensity: float = generate_interesting_pattern(self.x, self.y)
        detector_data = (
            self._full_intensity_blob
            * intensity
            * self.exposure
            / self.saturation_exposure_time
        ).astype(np.uint8)

        # Write the data and sum
        self.write_data_to_dataset(DATA_PATH, (self.height, self.width), detector_data)
        self.write_data_to_dataset(SUM_PATH, (), np.sum(detector_data))

        # counter increment is last
        # as only at this point the new data is visible from the outside
        self.image_counter += 1
        self._set_counter_signal(self.image_counter)

    def set_exposure(self, value: float) -> None:
        self.exposure = value

    def set_x(self, value: float) -> None:
        self.x = value

    def set_y(self, value: float) -> None:
        self.y = value

    async def open_file(
        self, path_provider: PathProvider, name: str, multiplier: int = 1
    ) -> dict[str, DataKey]:
        await self.counter_signal.connect()

        self.target_path = self._get_new_path(path_provider)
        self._path_provider = path_provider

        self._handle_for_h5_file = h5py.File(self.target_path, "w", libver="latest")

        assert self._handle_for_h5_file, "not loaded the file right"

        self._handle_for_h5_file.create_dataset(
            name=DATA_PATH,
            shape=(0, self.height, self.width),
            dtype=np.uint8,
            maxshape=(None, self.height, self.width),
        )
        self._handle_for_h5_file.create_dataset(
            name=SUM_PATH,
            shape=(0,),
            dtype=np.float64,
            maxshape=(None,),
        )

        # once datasets written, can switch the model to single writer multiple reader
        self._handle_for_h5_file.swmr_mode = True
        self.multiplier = multiplier

        outer_shape = (multiplier,) if multiplier > 1 else ()

        # cache state to self
        # Add the main data
        self._datasets = [
            HDFDataset(
                data_key=name,
                dataset=DATA_PATH,
                shape=(self.height, self.width),
                multiplier=multiplier,
            ),
            HDFDataset(
                f"{name}-sum",
                dataset=SUM_PATH,
                shape=(),
                multiplier=multiplier,
            ),
        ]

        describe = {
            ds.data_key: DataKey(
                source="sim://pattern-generator-hdf-file",
                shape=list(outer_shape) + list(ds.shape),
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    def _get_new_path(self, path_provider: PathProvider) -> Path:
        info = path_provider(device_name="pattern")
        new_path: Path = info.directory_path / info.filename
        return new_path

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
                self._hdf_stream_provider = HDFFile(
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
            self._handle_for_h5_file = None

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self.counter_signal, timeout=timeout):
            yield num_captured // self.multiplier
