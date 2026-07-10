import asyncio
import os
import subprocess
import time
from pathlib import Path

import h5py
import pytest

from ophyd_async.core import (
    DetectorTrigger,
    Device,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
)
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.fastcs.eiger import EigerDetector

SAVE_PATH = "/tmp"

_eiger_ioc = "EIGER-CI"
_odin_ioc = "ODIN-CI"
_eiger_ioc_image = "ghcr.io/diamondlightsource/eiger-fastcs:0.1.0beta5"
_odin_ioc_image = "ghcr.io/diamondlightsource/odin-fastcs:0.2.0beta2"

env = os.environ.copy()
env["eiger_ioc"] = _eiger_ioc
env["odin_ioc"] = _odin_ioc


class SetupDevice(Device):
    """Holds PVs that we would either expect to be initially set and
    never change or to be externally set in prod.
    """

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


@pytest.fixture(scope="session")
def eiger_ioc():
    # Start the IOC process
    command = (
        f"docker run --rm --name={_eiger_ioc} -dt --net=host -v /tmp/opi/:/epics/opi"
        f" {_eiger_ioc_image} ioc {_eiger_ioc}"
    )
    _ = subprocess.Popen(
        command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        # wait for IOC to be ready (sleep or poll)
        time.sleep(1)
        yield
    finally:
        # Cleanup: terminate the IOC process
        os.system(f"docker kill {_eiger_ioc}")


@pytest.fixture(scope="session")
def odin_ioc():
    # Start the IOC process
    command = (
        f"docker run --rm --name={_odin_ioc} -dt --net=host -v /tmp/opi/:/epics/opi"
        f" {_odin_ioc_image} ioc {_odin_ioc}"
    )
    _ = subprocess.Popen(
        command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        # wait for IOC to be ready (sleep or poll)
        time.sleep(1)
        yield
    finally:
        # Cleanup: terminate the IOC process
        os.system(f"docker kill {_odin_ioc}")


@pytest.fixture
def ioc_prefixes(eiger_ioc, odin_ioc):
    return _eiger_ioc + ":", _odin_ioc + ":"


@pytest.fixture
async def setup_device(RE, ioc_prefixes):
    async with init_devices():
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
    provider = StaticPathProvider(StaticFilenameProvider("test_eiger"), Path(SAVE_PATH))
    async with init_devices():
        test_eiger = EigerDetector("", provider, ioc_prefixes[0], ioc_prefixes[1])

    return test_eiger


@pytest.mark.skip(reason="Flaky test, see GH-819")
async def test_trigger_saves_file(test_eiger: EigerDetector, setup_device: SetupDevice):
    single_shot = TriggerInfo(
        exposure_timeout=None,
        number_of_events=1,
        trigger=DetectorTrigger.INTERNAL,
        livetime=None,
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
