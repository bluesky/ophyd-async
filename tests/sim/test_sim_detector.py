import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim.sim_pattern_generator import SimPatternDetector


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


async def test_detector_creates_controller_and_writer(
    sim_pattern_detector: SimPatternDetector,
):
    assert sim_pattern_detector.writer
    assert sim_pattern_detector.controller


async def test_writes_pattern_to_file(
    sim_pattern_detector: SimPatternDetector, sim_motor: motor.Motor, tmp_path
):
    sim_pattern_detector = SimPatternDetector(
        config_sigs=[*sim_motor._readables], path=tmp_path
    )

    images_number = 2
    await sim_pattern_detector.controller.arm(num=images_number)
    # assert that the file is created and non-empty
    assert sim_pattern_detector.writer

    # assert that the file contains data in expected dimensions


async def test_set_x_and_y(sim_pattern_detector):
    assert sim_pattern_detector.pattern_generator.x == 0
    sim_pattern_detector.pattern_generator.set_x(200)
    assert sim_pattern_detector.pattern_generator.x == 200


async def test_initial_blob(sim_pattern_detector: SimPatternDetector):
    assert sim_pattern_detector.pattern_generator.STARTING_BLOB.any()
