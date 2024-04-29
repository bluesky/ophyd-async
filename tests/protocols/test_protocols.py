from pathlib import Path

from bluesky.utils import new_uid

from ophyd_async import protocols as bs_protocols
from ophyd_async.core import (
    DeviceCollector,
    StaticDirectoryProvider,
    StaticFilenameProvider,
)
from ophyd_async.core.flyer import HardwareTriggeredFlyable
from ophyd_async.epics.areadetector.drivers import ADBase
from ophyd_async.epics.areadetector.writers import NDFileHDF
from ophyd_async.epics.demo.demo_ad_sim_detector import DemoADSimDetector
from ophyd_async.sim.demo import SimMotor


async def make_detector(prefix: str, name: str, tmp_path: Path):
    fp = StaticFilenameProvider(f"test-{new_uid()}")
    dp = StaticDirectoryProvider(fp, tmp_path)

    async with DeviceCollector(mock=True):
        drv = ADBase(f"{prefix}DRV:")
        hdf = NDFileHDF(f"{prefix}HDF:")
        det = DemoADSimDetector(
            drv, hdf, dp, config_sigs=[drv.acquire_time, drv.acquire], name=name
        )

    return det


async def test_readable():
    async with DeviceCollector(mock=True):
        det = await make_detector("test", "test det", Path("/tmp"))
    assert isinstance(SimMotor, bs_protocols.AsyncReadable)
    assert isinstance(det, bs_protocols.AsyncReadable)
    assert not isinstance(HardwareTriggeredFlyable, bs_protocols.AsyncReadable)
