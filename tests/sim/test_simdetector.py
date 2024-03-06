import numpy as np
import pytest

from ophyd_async.core.device import Device
from ophyd_async.sim.SimPatternDetector import SimPatternDetector


def test_writes_pattern_to_file():
    width, height = 100
    sim_motor = Device()
    file_path = "/tmp/test.h5"
    sim_pattern_detector = SimPatternDetector(
        config_sigs=sim_motor.rw, path=file_path, width=width, height=height
    )
    # assert that the file is created and non-empty
    # assert that the file contains data in expected dimensions
