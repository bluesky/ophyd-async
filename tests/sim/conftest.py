from pathlib import Path

import pytest
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.motion import motor
from ophyd_async.sim import SimDetector


@pytest.fixture
async def sim_pattern_detector(tmp_path_factory):
    path: Path = tmp_path_factory.mktemp("tmp")
    async with DeviceCollector(sim=True):
        sim_pattern_detector = SimDetector(name="PATTERN1", path=path)

    return sim_pattern_detector


