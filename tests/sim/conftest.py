from pathlib import Path

import pytest

from ophyd_async.sim.demo import PatternDetector


@pytest.fixture
async def sim_pattern_detector(tmp_path_factory) -> PatternDetector:
    path: Path = tmp_path_factory.mktemp("tmp")
    return PatternDetector(name="PATTERN1", path=path)
