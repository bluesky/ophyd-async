from pathlib import Path

import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.sim import SimPatternDetector


@pytest.fixture
async def sim_pattern_detector(tmp_path_factory) -> SimPatternDetector:
    path: Path = tmp_path_factory.mktemp("tmp")
    async with DeviceCollector(sim=True):
        sim_pattern_detector = SimPatternDetector(name="PATTERN1", path=path)

    return sim_pattern_detector
