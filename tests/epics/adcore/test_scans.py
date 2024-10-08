import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    DeviceCollector,
    FlyerController,
    StandardDetector,
    StandardFlyer,
    TriggerInfo,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector


class DummyTriggerLogic(FlyerController[int]):
    def __init__(self): ...

    async def prepare(self, value: int):
        return value

    async def kickoff(self): ...

    async def complete(self): ...

    async def stop(self): ...


class DummyController(DetectorController):
    def __init__(self) -> None: ...
    async def prepare(self, trigger_info: TriggerInfo):
        return AsyncStatus(asyncio.sleep(0.01))

    async def arm(self):
        self._arm_status = AsyncStatus(asyncio.sleep(0.01))

    async def wait_for_idle(self):
        await self._arm_status

    async def disarm(self): ...

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.002


@pytest.fixture
def controller(RE) -> adsimdetector.SimController:
    with DeviceCollector(mock=True):
        drv = adcore.ADBaseIO("DRV")

    return adsimdetector.SimController(drv)


@pytest.fixture
def writer(RE, static_path_provider, tmp_path: Path) -> adcore.ADHDFWriter:
    with DeviceCollector(mock=True):
        hdf = adcore.NDFileHDFIO("HDF")

    return adcore.ADHDFWriter(
        hdf,
        path_provider=static_path_provider,
        name_provider=lambda: "test",
        dataset_describer=AsyncMock(),
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

    detector: StandardDetector[TriggerInfo | None] = StandardDetector(
        controller, writer
    )
    trigger_logic = DummyTriggerLogic()

    flyer = StandardFlyer(trigger_logic, name="flyer")
    trigger_info = TriggerInfo(
        number_of_triggers=1,
        trigger=DetectorTrigger.constant_gate,
        deadtime=2,
        livetime=2,
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
