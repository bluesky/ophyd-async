from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim.PatternGenerator import PatternGenerator
from ophyd_async.sim.SimPatternDetector import SimPatternDetector




@pytest.fixture
async def sim_pattern_detector(tmp_path_factory):
    path:Path = tmp_path_factory.mktemp('/tmp')
    async with DeviceCollector(sim=True):
        sim_pattern_detector = SimPatternDetector("PATTERN1", path)

    assert sim_pattern_detector.name == "PATTERN1"
    yield sim_pattern_detector

def test_sim_pattern_detector_initialization(sim_pattern_detector: SimPatternDetector, ):
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


async def test_writes_pattern_to_file(sim_pattern_detector: SimPatternDetector):
    file_path = "/tmp/test.h5"
    # mydir = StaticDirectoryProvider(file_path)
    sim_motor = motor.Motor("test")
    sim_pattern_detector = SimPatternDetector(config_sigs=sim_motor.rw, path=file_path)

    images_number = 2
    sim_pattern_detector.controller.arm(num=images_number)
    # assert that the file is created and non-empty

    # assert that the file contains data in expected dimensions


# @pytest.fixture
# def writer(RE, tmp_path: Path) -> HDFWriter:
#     with DeviceCollector(sim=True):
#         hdf = NDFileHDF("HDF")

#     return HDFWriter(
#         hdf,
#         directory_provider=StaticDirectoryProvider(tmp_path),
#         name_provider=lambda: "test",
#         shape_provider=AsyncMock(),
#     )
