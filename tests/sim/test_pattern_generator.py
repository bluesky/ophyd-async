from unittest.mock import MagicMock, patch

import pytest

from ophyd_async.sim import PatternGenerator


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


def test_write_data_to_dataset_no_file_opened(pattern_generator: PatternGenerator):
    with pytest.raises(OSError, match="No file has been opened!"):
        pattern_generator.write_data_to_dataset("test_path", (10,), MagicMock())


def test_write_data_to_dataset_invalid_type(pattern_generator: PatternGenerator):
    pattern_generator._handle_for_h5_file = {"test_path": MagicMock()}  # type: ignore
    with pytest.raises(
        TypeError, match="Expected test_path to be a dataset, got MagicMock"
    ):
        pattern_generator.write_data_to_dataset("test_path", (10,), MagicMock())


@pytest.mark.asyncio
async def test_open_file_not_loaded(pattern_generator: PatternGenerator) -> None:
    with patch("h5py.File", return_value=None):
        with pytest.raises(OSError, match=r"Problem opening file .*"):
            await pattern_generator.open_file(MagicMock(), "test_name")


@pytest.mark.asyncio
async def test_collect_stream_docs_runtime_error(pattern_generator: PatternGenerator):
    pattern_generator._handle_for_h5_file = MagicMock()
    pattern_generator._handle_for_h5_file.flush = MagicMock()
    pattern_generator.target_path = None

    with pytest.raises(RuntimeError, match="open file has not been called"):
        async for _ in pattern_generator.collect_stream_docs(1):
            pass
