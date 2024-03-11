import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim.SimPatternDetector import SimPatternDetector


@pytest.t
def test_writes_pattern_to_file():
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
