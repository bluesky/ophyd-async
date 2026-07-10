from __future__ import annotations

import asyncio
import time
from pathlib import PurePath

import h5py
import numpy as np

from ophyd_async.core import soft_signal_r_and_setter

# raw data path
DATA_PATH = "/entry/data/data"

# pixel sum path
SUM_PATH = "/entry/sum"


def generate_gaussian_blob(height: int, width: int) -> np.ndarray:
    """Make a Gaussian Blob with float values in range 0..1."""
    x, y = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    d = np.sqrt(x * x + y * y)
    blob = np.exp(-(d**2))
    return blob


def generate_interesting_pattern(
    x: float, y: float, channel: int, offset: float
) -> float:
    """Return a float value in range 0..1.

    Interesting in x and y in range -10..10
    """
    return (np.sin(x) ** channel + np.cos(x * y + offset) + 2) / 4


class PatternFile:
    def __init__(
        self,
        path: PurePath,
        width: int = 320,
        height: int = 240,
    ):
        self.file = h5py.File(path, "w", libver="latest")
        self.data = self.file.create_dataset(
            name=DATA_PATH,
            shape=(0, height, width),
            dtype=np.uint8,
            maxshape=(None, height, width),
            chunks=(1, height, width),
        )
        self.sum = self.file.create_dataset(
            name=SUM_PATH,
            shape=(0,),
            dtype=np.int64,
            maxshape=(None,),
            chunks=(1024,),
        )
        # Once datasets written, can switch the model to single writer multiple reader
        self.file.swmr_mode = True
        self.blob = generate_gaussian_blob(height, width) * np.iinfo(np.uint8).max
        self.image_counter = 0

    def write_image_to_file(self, intensity: float):
        data = np.floor(self.blob * intensity)
        for dset, value in ((self.data, data), (self.sum, np.sum(data))):
            dset.resize(self.image_counter + 1, axis=0)
            dset[self.image_counter] = value
            dset.flush()
        self.image_counter += 1

    def close(self):
        self.file.close()


class PatternGenerator:
    """Generates pattern images in files."""

    def __init__(self, sleep=asyncio.sleep):
        self._x = 0.0
        self._y = 0.0
        self._file: PatternFile | None = None
        self._exposure: float = 0.1
        self._period: float = 0.2
        self._number_of_frames: int = 10
        self.sleep = sleep
        self.images_written, self._update_images_written = soft_signal_r_and_setter(int)

    def set_x(self, x: float):
        self._x = x

    def set_y(self, y: float):
        self._y = y

    def generate_point(self, channel: int = 1, high_energy: bool = False) -> float:
        """Make a point between 0 and 1 based on x and y."""
        offset = 100 if high_energy else 10
        return generate_interesting_pattern(self._x, self._y, channel, offset)

    def open_file(self, path: PurePath, width: int, height: int):
        self._file = PatternFile(path, width, height)
        self._update_images_written(0)

    def _get_file(self) -> PatternFile:
        if not self._file:
            raise RuntimeError("open_file not run")
        return self._file

    def setup_acquisition_parameters(
        self, exposure: float, period: float, number_of_frames: int
    ):
        self._exposure = exposure or self._exposure
        self._period = period or self._period
        self._number_of_frames = number_of_frames

    async def write_images_to_file(self):
        file = self._get_file()
        start = time.monotonic()
        for i in range(1, self._number_of_frames + 1):
            deadline = start + i * self._period
            timeout = deadline - time.monotonic()
            await self.sleep(timeout)
            intensity = self.generate_point() * self._exposure
            file.write_image_to_file(intensity)
            self._update_images_written(file.image_counter)

    def close_file(self):
        if self._file:
            self._file.close()
            self._file = None
