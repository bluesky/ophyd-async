from pathlib import Path

from bluesky.utils import new_uid

from ophyd_async.core import (AsyncReadable, DeviceCollector, StandardFlyer,
                              StaticDirectoryProvider)
from ophyd_async.epics.adcore import ADBase, NDFileHDF
from ophyd_async.epics.adsimdetector import SimDetector
from ophyd_async.sim import demo


async def make_detector(prefix: str, name: str, tmp_path: Path):
    dp = StaticDirectoryProvider(tmp_path, f"test-{new_uid()}")

    async with DeviceCollector(mock=True):
        drv = ADBase(f"{prefix}DRV:")
        hdf = NDFileHDF(f"{prefix}HDF:")
        det = SimDetector(
            drv, hdf, dp, config_sigs=[drv.acquire_time, drv.acquire], name=name
        )

    return det


async def test_readable():
    async with DeviceCollector(mock=True):
        det = await make_detector("test", "test det", Path("/tmp"))
    assert isinstance(demo.SimMotor, AsyncReadable)
    assert isinstance(det, AsyncReadable)
    assert not isinstance(StandardFlyer, AsyncReadable)
