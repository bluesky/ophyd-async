from pathlib import Path
from typing import Optional

import h5py
import numpy as np

from ophyd_async.core import DirectoryProvider


def make_gaussian_blob(height: int, width: int) -> np.ndarray:
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
# pixel sum path
SUM_PATH = "/entry/sum"


class PatternGenerator:
    """
    order of events
    1. a definition of a new scan is created
    2. file is opened
        - before anythign else happens,
        - descriptors are defined and sent to bluesky for each dataset
    3. exposure time is set
    4. x and y are set -
    5. interesting pattern is made
    6. image is written to file
    7. number of images is incremented
    8. x and y move to next position
    9. when all x and y are done, file is closed
    """

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
        self.initial_blob = (
            make_gaussian_blob(width=detector_width, height=detector_height)
            * np.uint8.max
        )
        self.file: Optional[h5py.File] = None

    async def write_image_to_file(self) -> None:
        assert self.file, "no file has been opened!"
        self.file.create_dataset(
            name=f"pattern-generator-file-{self.written_images_counter}",
            dtype=np.ndarray,
        )

        # prepare - resize the fixed hdf5 data structure
        # so that the new image can be written
        target_dimensions = (
            self.written_images_counter + 1,
            self.height,
            self.width,
        )
        self.file[DATA_PATH].resize(target_dimensions)
        self.file[SUM_PATH].resize(self.written_images_counter + 1)

        # generate the simulated data
        intensity: float = interesting_pattern(self.x, self.y)
        detector_data: np.uint8 = (
            self.blob * intensity * self.exposure / self.saturation_exposure_time
        ).astype(np.uint8)

        # write data to disc (intermediate step)
        self.file[DATA_PATH][self.written_images_counter] = detector_data
        self.file[SUM_PATH][self.written_images_counter] = np.sum(detector_data)

        # save metadata - so that it's discoverable
        self.file[DATA_PATH].flush()
        self.file[SUM_PATH].flush()

        # coutner increment is last
        # as only at this point the new data is visible from the outside
        self.written_images_counter += 1

    def set_exposure(self, value: float) -> None:
        self.exposure = value

    def set_x(self, value: float) -> None:
        self.x = value

    def set_y(self, value: float) -> None:
        self.y = value

    def open_file(self, dir: DirectoryProvider) -> None:
        new_path: Path = dir().resource_dir
        hdf5_file = h5py.File(new_path, "w")
        hdf5_file.create_dataset(
            DATA_PATH,
            dtype=np.uint8,
            shape=(1, self.height, self.width),
            maxshape=(None, self.height, self.width),
        )

        hdf5_file.create_dataset(
            SUM_PATH,
            dtype=np.float64,
            shape=(1,),
            maxshape=(None),
            fillvalue=-1,
        )
        hdf5_file.swmr_mode = True
        self.file = hdf5_file
        print("file opened")

    def close(self) -> None:
        self.file.close()
        print("file closed")
        self.file = None
