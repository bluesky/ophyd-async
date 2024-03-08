from pathlib import Path
from typing import Optional
import h5py
import numpy as np
from ophyd_async.core import DirectoryProvider


def make_gaussian_blob(width: int, height: int) -> np.ndarray:
    """Make a Gaussian Blob with float values in range 0..1"""
    x, y = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    d = np.sqrt(x * x + y * y)
    blob = np.exp(-(d**2))
    return blob


def interesting_pattern(x: float, y: float) -> float:
    """This function is interesting in x and y in range -10..10, returning
    a float value in range 0..1
    """
    z = 0.5 + (np.sin(x) ** 10 + np.cos(10 + y * x) * np.cos(x)) / 2
    return z


# raw data path
DATA_PATH = "/entry/data/data"
# blobs path
UID_PATH = "/entry/uid"
# pixel sum path
SUM_PATH = "/entry/sum"

DEFAULT_WIDTH = 100
DEFAULT_HEIGHT = 100


class PatternGenerator:
    """
    order of events
    1. a definition of a new scan is created
    2. file is opened
    3. exposure time is set
    4. x and y are set
    5. interesting pattern is made
    6. image is written to file
    7. number of images is incremented
    8. x and y move to next position
    9. when all x and y are done, file is closed
    """

    exposure: float
    x: float
    y: float
    initial_blob: np.ndarray
    file: Optional[h5py.File]
    indices_written: int

    def __init__(self, exposure: float = 0.01) -> None:
        self.exposure = exposure
        self.initial_blob = make_gaussian_blob(width=100, height=100) * 255

    async def write_image_to_file(self, counter: int, image: np.ndarray):
        assert self.file, "no file has been opened!"
        self.file.create_dataset(
            name=f"pattern-generator-file-{counter}", dtype=np.ndarray
        )
        await self.file.flush_now.set(True)

    def set_exposure(self, value: float) -> None:
        self.exposure = value

    def set_x(self, value: float) -> None:
        self.x = value

    def set_y(self, value: float) -> None:
        self.y = value

    def open_file(self, dir: DirectoryProvider) -> None:
        new_path: Path = dir().resource_dir
        hdf5_file = h5py.File(new_path, "w")
        height = DEFAULT_HEIGHT
        width = DEFAULT_WIDTH
        hdf5_file.create_dataset(
            DATA_PATH,
            dtype=np.uint8,
            shape=(1, height, width),
            maxshape=(None, height, width),
        )

        hdf5_file.create_dataset(
            UID_PATH,
            dtype=np.int32,
            shape=(1, 1, 1),
            maxshape=(None, 1, 1),
            fillvalue=-1,
        )

        hdf5_file.create_dataset(
            SUM_PATH,
            dtype=np.float64,
            shape=(1, 1, 1),
            maxshape=(None, 1, 1),
            fillvalue=-1,
        )
        hdf5_file.swmr_mode = True
        self.file = hdf5_file
