import pytest

from ophyd_async.sim.demo import PatternGenerator


@pytest.fixture
async def pattern_generator():
    # path: Path = tmp_path_factory.mktemp("tmp")
    pattern_generator = PatternGenerator()
    yield pattern_generator


async def test_init(pattern_generator: PatternGenerator):
    assert pattern_generator.exposure == 0.1
    assert pattern_generator.height == 240
    assert pattern_generator.width == 320
    assert pattern_generator.image_counter == 0
    assert pattern_generator._handle_for_h5_file is None
    assert pattern_generator._full_intensity_blob.shape == (240, 320)


def test_set_exposure(pattern_generator: PatternGenerator):
    pattern_generator.set_exposure(0.5)
    assert pattern_generator.exposure == 0.5


def test_set_x(pattern_generator: PatternGenerator):
    pattern_generator.set_x(5.0)
    assert pattern_generator.x == 5.0


def test_set_y(pattern_generator: PatternGenerator):
    pattern_generator.set_y(-3.0)
    assert pattern_generator.y == -3.0
