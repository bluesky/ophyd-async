from pathlib import Path

from bluesky.utils import new_uid

from ophyd_async.core import (
    AsyncReadable,
    StandardFlyer,
    StaticFilenameProvider,
    StaticPathProvider,
    init_devices,
)
from ophyd_async.epics import adsimdetector
from ophyd_async.sim import SimMotor


async def make_detector(prefix: str, name: str, tmp_path: Path):
    fp = StaticFilenameProvider(f"test-{new_uid()}")
    dp = StaticPathProvider(fp, tmp_path)

    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(prefix, dp, name=name)

    det._config_sigs = [det.drv.acquire_time, det.drv.acquire]

    return det


async def test_readable():
    async with init_devices(mock=True):
        det = await make_detector("test", "test det", Path("/tmp"))
    assert isinstance(SimMotor, AsyncReadable)
    assert isinstance(det, AsyncReadable)
    assert not isinstance(StandardFlyer, AsyncReadable)
