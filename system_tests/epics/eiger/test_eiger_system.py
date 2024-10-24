import asyncio
import os
from pathlib import Path

import h5py
import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    Device,
    DeviceCollector,
    StaticPathProvider,
)
from ophyd_async.epics.eiger import EigerDetector, EigerTriggerInfo
from ophyd_async.epics.signal import epics_signal_rw

SAVE_PATH = "/tmp"


class SetupDevice(Device):
    """Holds PVs that we would either expect to be initially set and
    never change or to be externally set in prod."""

    def __init__(self, eiger_prefix: str, odin_prefix: str) -> None:
        self.trigger = epics_signal_rw(int, f"{eiger_prefix}Trigger")
        self.header_detail = epics_signal_rw(str, f"{eiger_prefix}HeaderDetail")
        self.compression = epics_signal_rw(str, f"{odin_prefix}DatasetDataCompression")
        self.frames_per_block = epics_signal_rw(
            int, f"{odin_prefix}ProcessFramesPerBlock"
        )
        self.blocks_per_file = epics_signal_rw(
            int, f"{odin_prefix}ProcessBlocksPerFile"
        )
        super().__init__("")


@pytest.fixture
def ioc_prefixes():
    return os.environ["eiger_ioc"] + ":", os.environ["odin_ioc"] + ":"


@pytest.fixture
def RE():
    return RunEngine()


@pytest.fixture
async def setup_device(RE, ioc_prefixes):
    async with DeviceCollector():
        device = SetupDevice(ioc_prefixes[0], ioc_prefixes[1] + "FP:")
    await asyncio.gather(
        device.header_detail.set("all"),
        device.compression.set("BSLZ4"),
        device.frames_per_block.set(1000),
        device.blocks_per_file.set(1),
    )

    return device


@pytest.fixture
async def test_eiger(RE, ioc_prefixes) -> EigerDetector:
    provider = StaticPathProvider(lambda: "test_eiger", Path(SAVE_PATH))
    async with DeviceCollector():
        test_eiger = EigerDetector("", provider, ioc_prefixes[0], ioc_prefixes[1])

    return test_eiger


async def test_trigger_saves_file(test_eiger: EigerDetector, setup_device: SetupDevice):
    single_shot = EigerTriggerInfo(
        frame_timeout=None,
        number_of_triggers=1,
        trigger=DetectorTrigger.internal,
        deadtime=None,
        livetime=None,
        energy_ev=10000,
    )

    await test_eiger.stage()
    await test_eiger.prepare(single_shot)
    # Need to work out what the hold up is in prepare so we cant do this straight away.
    # File path propogation?
    await asyncio.sleep(0.5)
    await setup_device.trigger.set(1)
    await asyncio.sleep(0.5)  # Need to work out when it's actually finished writing
    await test_eiger.unstage()

    with h5py.File(SAVE_PATH + "/test_eiger_000001.h5") as f:
        assert "data" in f.keys()
        assert len(f["data"]) == 1
