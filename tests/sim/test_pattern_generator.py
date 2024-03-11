from unittest import MagicMock

import h5py
import numpy as np
import pytest

from ophyd_async.sim.PatternGenerator import DATA_PATH, SUM_PATH, PatternGenerator


@pytest.fixture
def tmp_hdf5_file(tmp_path):
    file = tmp_path / "test_file.hdf5"
    return file


@pytest.fixture
def pattern_generator():
    return PatternGenerator()


async def test_init():

    from ophyd_async.sim.PatternGenerator import PatternGenerator

    pattern_generator = PatternGenerator()
    assert pattern_generator.exposure == 1
    assert pattern_generator.height == 240
    assert pattern_generator.width == 320
    assert pattern_generator.written_images_counter == 0
    assert pattern_generator.file is None
    assert pattern_generator.initial_blob.shape == (240, 320)


def test_initialization(pattern_generator):
    assert pattern_generator.saturation_exposure_time == 1
    assert pattern_generator.exposure == 1
    assert pattern_generator.x == 0.0
    assert pattern_generator.y == 0.0
    assert pattern_generator.height == 240
    assert pattern_generator.width == 320
    assert pattern_generator.written_images_counter == 0
    assert isinstance(pattern_generator.initial_blob, np.ndarray)


async def test_open_and_close_file(tmp_hdf5_file, pattern_generator):
    dir_provider = MagicMock(return_value=tmp_hdf5_file.parent)
    pattern_generator.open_file(dir_provider)
    assert pattern_generator.file is not None
    assert isinstance(pattern_generator.file, h5py.File)
    pattern_generator.close()
    assert pattern_generator.file is None


def test_set_exposure(pattern_generator):
    pattern_generator.set_exposure(0.5)
    assert pattern_generator.exposure == 0.5


def test_set_x(pattern_generator):
    pattern_generator.set_x(5.0)
    assert pattern_generator.x == 5.0


def test_set_y(pattern_generator):
    pattern_generator.set_y(-3.0)
    assert pattern_generator.y == -3.0


@pytest.mark.asyncio
async def test_write_image_to_file(tmp_hdf5_file, pattern_generator):
    dir_provider = MagicMock(return_value=tmp_hdf5_file.parent)
    pattern_generator.open_file(dir_provider)  # Open file for real to simplify

    await pattern_generator.write_image_to_file()
    assert pattern_generator.written_images_counter == 1
    assert DATA_PATH in pattern_generator.file
    assert SUM_PATH in pattern_generator.file

    pattern_generator.close()  # Clean up
