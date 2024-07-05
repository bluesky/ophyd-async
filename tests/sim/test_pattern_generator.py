import h5py
import numpy as np
import pytest

from ophyd_async.core import StaticDirectoryProvider
from ophyd_async.sim.pattern_generator import DATA_PATH, SUM_PATH, PatternGenerator


@pytest.fixture
async def pattern_generator():
    # path: Path = tmp_path_factory.mktemp("tmp")
    pattern_generator = PatternGenerator()
    yield pattern_generator


async def test_init(pattern_generator: PatternGenerator):
    assert pattern_generator.exposure == 1
    assert pattern_generator.height == 240
    assert pattern_generator.width == 320
    assert pattern_generator.written_images_counter == 0
    assert pattern_generator._handle_for_h5_file is None
    assert pattern_generator.STARTING_BLOB.shape == (240, 320)


def test_initialization(pattern_generator: PatternGenerator):
    assert pattern_generator.saturation_exposure_time == 1
    assert pattern_generator.exposure == 1
    assert pattern_generator.x == 0.0
    assert pattern_generator.y == 0.0
    assert pattern_generator.height == 240
    assert pattern_generator.width == 320
    assert pattern_generator.written_images_counter == 0
    assert isinstance(pattern_generator.STARTING_BLOB, np.ndarray)
    assert pattern_generator.shape == [
        pattern_generator.height,
        pattern_generator.width,
    ]
    assert pattern_generator.maxshape == (
        None,
        pattern_generator.height,
        pattern_generator.width,
    )


@pytest.mark.asyncio
async def test_open_and_close_file(tmp_path, pattern_generator: PatternGenerator):
    dir_provider = StaticDirectoryProvider(str(tmp_path))
    await pattern_generator.open_file(dir_provider)
    assert pattern_generator._handle_for_h5_file is not None
    assert isinstance(pattern_generator._handle_for_h5_file, h5py.File)
    pattern_generator.close()
    assert pattern_generator._handle_for_h5_file is None


def test_set_exposure(pattern_generator: PatternGenerator):
    pattern_generator.set_exposure(0.5)
    assert pattern_generator.exposure == 0.5


def test_set_x(pattern_generator: PatternGenerator):
    pattern_generator.set_x(5.0)
    assert pattern_generator.x == 5.0


def test_set_y(pattern_generator: PatternGenerator):
    pattern_generator.set_y(-3.0)
    assert pattern_generator.y == -3.0


@pytest.mark.asyncio
async def test_write_image_to_file(tmp_path, pattern_generator: PatternGenerator):
    dir_provider = StaticDirectoryProvider(str(tmp_path))
    await pattern_generator.open_file(dir_provider)

    await pattern_generator.write_image_to_file()
    assert pattern_generator.written_images_counter == 1
    assert pattern_generator._handle_for_h5_file
    assert DATA_PATH in pattern_generator._handle_for_h5_file
    assert SUM_PATH in pattern_generator._handle_for_h5_file

    pattern_generator.close()  # Clean up
