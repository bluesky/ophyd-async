from pathlib import Path

from bluesky.utils import new_uid

from ophyd_async.core import (AsyncReadable, DeviceCollector,
                              StandardFlyer, StaticFilenameProvider,
                              StaticPathProvider)
from ophyd_async.epics import adcore, adsimdetector
from ophyd_async.sim.demo import SimMotor


async def make_detector(prefix: str, name: str, tmp_path: Path):
    fp = StaticFilenameProvider(f"test-{new_uid()}")
    dp = StaticPathProvider(fp, tmp_path)

    async with DeviceCollector(mock=True):
        drv = adcore.ADBase(f"{prefix}DRV:")
        hdf = adcore.NDFileHDF(f"{prefix}HDF:")
        det = adsimdetector.SimDetector(
            drv, hdf, dp, config_sigs=[drv.acquire_time, drv.acquire], name=name
        )

    return det


async def test_readable():
    async with DeviceCollector(mock=True):
        det = await make_detector("test", "test det", Path("/tmp"))
    assert isinstance(SimMotor, AsyncReadable)
    assert isinstance(det, AsyncReadable)
    assert not isinstance(StandardFlyer, AsyncReadable)
