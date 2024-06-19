from pathlib import Path

import pytest

from ophyd_async.core import DeviceCollector
from ophyd_async.sim import demo


@pytest.fixture
async def sim_pattern_detector(tmp_path_factory) -> demo.SimPatternDetector:
    path: Path = tmp_path_factory.mktemp("tmp")
    async with DeviceCollector(mock=True):
        sim_pattern_detector = demo.SimPatternDetector(name="PATTERN1", path=path)

    return sim_pattern_detector
