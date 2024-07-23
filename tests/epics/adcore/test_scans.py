import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    DeviceCollector,
    StandardDetector,
    StandardFlyer,
    TriggerInfo,
    TriggerLogic,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self): ...

    async def prepare(self, value: int):
        return value

    async def kickoff(self): ...

    async def complete(self): ...

    async def stop(self): ...


class DummyController(DetectorControl):
    def __init__(self) -> None: ...

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        return AsyncStatus(asyncio.sleep(0.1))

    async def disarm(self): ...

    def get_deadtime(self, exposure: float) -> float:
        return 0.002


@pytest.fixture
def controller(RE) -> adsimdetector.SimController:
    with DeviceCollector(mock=True):
        drv = adcore.ADBase("DRV")

    return adsimdetector.SimController(drv)


@pytest.fixture
def writer(RE, static_path_provider, tmp_path: Path) -> adcore.ADHDFWriter:
    with DeviceCollector(mock=True):
        hdf = adcore.NDFileHDF("HDF")

    return adcore.ADHDFWriter(
        hdf,
        path_provider=static_path_provider,
        name_provider=lambda: "test",
        shape_provider=AsyncMock(),
    )


@patch("ophyd_async.core._detector.DEFAULT_TIMEOUT", 0.1)
async def test_hdf_writer_fails_on_timeout_with_stepscan(
    RE: RunEngine,
    writer: adcore.ADHDFWriter,
    controller: adsimdetector.SimController,
):
    set_mock_value(writer.hdf.file_path_exists, True)
    detector: StandardDetector[Any] = StandardDetector(
        controller, writer, name="detector"
    )

    with pytest.raises(Exception) as exc:
        RE(bp.count([detector]))

    assert isinstance(exc.value.__cause__, asyncio.TimeoutError)


@patch("ophyd_async.core._detector.DEFAULT_TIMEOUT", 0.1)
def test_hdf_writer_fails_on_timeout_with_flyscan(
    RE: RunEngine, writer: adcore.ADHDFWriter
):
    controller = DummyController()
    set_mock_value(writer.hdf.file_path_exists, True)

    detector: StandardDetector[Optional[TriggerInfo]] = StandardDetector(
        controller, writer
    )
    trigger_logic = DummyTriggerLogic()

    flyer = StandardFlyer(trigger_logic, [], name="flyer")
    trigger_info = TriggerInfo(
        number=1, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
    )

    def flying_plan():
        """NOTE: the following is a workaround to ensure tests always pass.
        See https://github.com/bluesky/bluesky/issues/1630 for more details.
        """
        yield from bps.stage_all(detector, flyer)
        try:
            # Prepare the flyer first to get the trigger info for the detectors
            yield from bps.prepare(flyer, 1, wait=True)
            # prepare detector second.
            yield from bps.prepare(detector, trigger_info, wait=True)
            yield from bps.open_run()
            yield from bps.kickoff(flyer)
            yield from bps.kickoff(detector)
            yield from bps.complete(flyer, wait=True)
            yield from bps.complete(detector, wait=True)
            yield from bps.close_run()
        finally:
            yield from bps.unstage_all(detector, flyer)

    with pytest.raises(Exception) as exc:
        RE(flying_plan())

    assert isinstance(exc.value.__cause__, asyncio.TimeoutError)
