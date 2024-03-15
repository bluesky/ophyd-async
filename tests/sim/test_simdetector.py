from pathlib import Path

import pytest
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim.SimPatternDetector import SimPatternDetector

# todo make tests that integration test the writer
# do IO tetsing like in files: `test_writers`, `test_panda`, `test_device_save_loader`


@pytest.fixture
async def sim_pattern_detector(tmp_path_factory):
    path: Path = tmp_path_factory.mktemp("tmp")
    async with DeviceCollector(sim=True):
        sim_pattern_detector = SimPatternDetector(name="PATTERN1", path=path)

    return sim_pattern_detector


@pytest.fixture
async def sim_motor():
    async with DeviceCollector(sim=True):
        sim_motor = motor.Motor("test")
    return sim_motor


async def test_sim_pattern_detector_initialization(
    sim_pattern_detector: SimPatternDetector,
):
    assert (
        sim_pattern_detector.pattern_generator
    ), "PatternGenerator was not initialized correctly."
    assert (
        sim_pattern_detector.writer.patternGenerator
    ), "Writer was not initialized with the correct PatternGenerator."
    assert (
        sim_pattern_detector.controller.pattern_generator
    ), "Controller was not initialized with the correct PatternGenerator."


async def test_detector_creates_controller_and_writer(
    sim_pattern_detector: SimPatternDetector,
):
    assert sim_pattern_detector.writer
    assert sim_pattern_detector.controller


async def test_writes_pattern_to_file(
    sim_pattern_detector: SimPatternDetector, sim_motor: motor.Motor
):
    file_path = "/tmp"
    # mydir = StaticDirectoryProvider(file_path)
    sim_pattern_detector = SimPatternDetector(
        config_sigs=[sim_motor.describe], path=file_path
    )

    images_number = 2
    await sim_pattern_detector.controller.arm(num=images_number)
    # assert that the file is created and non-empty

    # assert that the file contains data in expected dimensions


async def test_exposure(sim_pattern_detector):
    pass


async def test_set_x_and_y(sim_pattern_detector):
    pass


async def test_initial_blob(sim_pattern_detector):
    assert sim_pattern_detector.pattern_generator.initial_blob.any()


async def test_open_and_close_file(sim_pattern_detector):
    pass
