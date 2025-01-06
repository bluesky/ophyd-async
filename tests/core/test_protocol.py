from pathlib import Path

import pytest

from ophyd_async.core import (
    AsyncReadable,
    StandardFlyer,
)
from ophyd_async.sim import SimMotor


@pytest.mark.parametrize(
    "sim_detector", [("test", "test det", Path("/tmp"))], indirect=True
)
async def test_readable(sim_detector):
    assert isinstance(SimMotor, AsyncReadable)
    assert isinstance(sim_detector, AsyncReadable)
    assert not isinstance(StandardFlyer, AsyncReadable)
