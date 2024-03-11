from unittest.mock import MagicMock

import pytest
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim.PatternGenerator import PatternGenerator
from ophyd_async.sim.SimPatternDetector import SimPatternDetector


@pytest.fixture
def mock_pattern_generator():
    return MagicMock(spec=PatternGenerator)


@pytest.fixture
def sim_pattern_detector(mock_pattern_generator):
    # Assume default values for unspecified arguments for simplicity
    detector = SimPatternDetector(config_sigs=[], writer_timeout=10, path="/tmp")
    detector.pattern_generator = mock_pattern_generator
    return detector


def test_sim_pattern_detector_initialization(
    sim_pattern_detector, mock_pattern_generator
):
    assert (
        sim_pattern_detector.pattern_generator is mock_pattern_generator
    ), "PatternGenerator was not initialized correctly."
    assert (
        sim_pattern_detector.writer.patternGenerator is mock_pattern_generator
    ), "Writer was not initialized with the correct PatternGenerator."
    assert (
        sim_pattern_detector.controller.pattern_generator is mock_pattern_generator
    ), "Controller was not initialized with the correct PatternGenerator."


async def test_writes_pattern_to_file():
    width, height = 100
    async with DeviceCollector(sim=True):
        sim_motor = motor.Motor("test")
    file_path = "/tmp/test.h5"
    # mydir = StaticDirectoryProvider(file_path)
    sim_pattern_detector = SimPatternDetector(
        config_sigs=sim_motor.rw, path=file_path, width=width, height=height
    )
    images_number = 2
    sim_pattern_detector.controller.arm(num=images_number)
    # assert that the file is created and non-empty

    # assert that the file contains data in expected dimensions

@pytest.fixture
def writer(RE, tmp_path: Path) -> HDFWriter:
    with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF")

    return HDFWriter(
        hdf,
        directory_provider=StaticDirectoryProvider(tmp_path),
        name_provider=lambda: "test",
        shape_provider=AsyncMock(),
    )
