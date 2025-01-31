from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import h5py
import numpy as np

# raw data path
DATA_PATH = "/entry/data/data"

# pixel sum path
SUM_PATH = "/entry/sum"


def generate_gaussian_blob(height: int, width: int) -> np.ndarray:
    """Make a Gaussian Blob with float values in range 0..1"""
    x, y = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    d = np.sqrt(x * x + y * y)
    blob = np.exp(-(d**2))
    return blob


def generate_interesting_pattern(
    x: float, y: float, channel: int, offset: float
) -> float:
    """This function is interesting in x and y in range -10..10, returning
    a float value in range 0..1
    """
    return (np.sin(x) ** channel + np.cos(x * y + offset) + 2) / 4


class PatternFile:
    def __init__(
        self,
        path: Path,
        width: int = 320,
        height: int = 240,
    ):
        self.file = h5py.File(path, "w", libver="latest")
        self.data = self.file.create_dataset(
            name=DATA_PATH,
            shape=(0, height, width),
            dtype=np.uint8,
            maxshape=(None, height, width),
        )
        self.sum = self.file.create_dataset(
            name=SUM_PATH,
            shape=(0,),
            dtype=np.int64,
            maxshape=(None,),
        )
        # Once datasets written, can switch the model to single writer multiple reader
        self.file.swmr_mode = True
        self.blob = generate_gaussian_blob(height, width) * np.iinfo(np.uint8).max
        self.image_counter = 0
        self.q = asyncio.Queue()

    def write_image_to_file(self, intensity: float):
        data = np.floor(self.blob * intensity)
        for dset, value in ((self.data, data), (self.sum, np.sum(data))):
            dset.resize(self.image_counter + 1, axis=0)
            dset[self.image_counter] = value
            dset.flush()
        self.q.put_nowait(self.image_counter)
        self.image_counter += 1

    def close(self):
        self.file.close()


class PatternGenerator:
    """Generates pattern images in files."""

    def __init__(self):
        self._x = 0.0
        self._y = 0.0
        self._file: PatternFile | None = None

    def set_x(self, x: float):
        self._x = x

    def set_y(self, y: float):
        self._y = y

    def generate_point(self, channel: int = 1, high_energy: bool = False) -> float:
        """Make a point between 0 and 1 based on x and y"""
        offset = 100 if high_energy else 10
        return generate_interesting_pattern(self._x, self._y, channel, offset)

    def open_file(self, path: Path, width: int, height: int):
        self._file = PatternFile(path, width, height)

    def _get_file(self) -> PatternFile:
        if not self._file:
            raise RuntimeError("open_file not run")
        return self._file

    def write_image_to_file(self, exposure: float):
        self._get_file().write_image_to_file(self.generate_point() * exposure)

    async def observe_indices_written(self, timeout: float) -> AsyncGenerator[int]:
        file = self._get_file()
        if file.image_counter:
            yield file.image_counter
        while True:
            yield await asyncio.wait_for(file.q.get(), timeout)

    async def get_last_index(self) -> int:
        return self._get_file().image_counter

    def close_file(self):
        if self._file:
            self._file.close()
            self._file = None
