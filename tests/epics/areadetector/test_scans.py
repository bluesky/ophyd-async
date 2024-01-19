import asyncio
from pathlib import Path
from typing import Optional
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
    HardwareTriggeredFlyable,
    StandardDetector,
    StaticDirectoryProvider,
    TriggerInfo,
    TriggerLogic,
    set_sim_value,
)
from ophyd_async.epics.areadetector.controllers import ADSimController
from ophyd_async.epics.areadetector.drivers import ADBase
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self): ...

    def trigger_info(self, value: int) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
        )

    async def prepare(self, value: int):
        return value

    async def start(self): ...

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
def controller(RE) -> ADSimController:
    with DeviceCollector(sim=True):
        drv = ADBase("DRV")

    return ADSimController(drv)


@pytest.fixture
def writer(RE, tmp_path: Path) -> HDFWriter:
    with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF")

    return HDFWriter(
        hdf,
        directory_provider=StaticDirectoryProvider(tmp_path),
        name_provider=lambda: "test",
        shape_provider=AsyncMock(),
    )


@patch("ophyd_async.epics.areadetector.utils.wait_for_value", return_value=None)
@patch("ophyd_async.core.detector.DEFAULT_TIMEOUT", 0.1)
async def test_hdf_writer_fails_on_timeout_with_stepscan(
    patched_wait_for_value,
    RE: RunEngine,
    writer: HDFWriter,
    controller: ADSimController,
):
    set_sim_value(writer.hdf.file_path_exists, True)
    detector = StandardDetector(
        controller, writer, name="detector", writer_timeout=0.01
    )

    with pytest.raises(Exception) as exc:
        RE(bp.count([detector]))

    assert isinstance(exc.value.__cause__, TimeoutError)


@patch("ophyd_async.epics.areadetector.utils.wait_for_value", return_value=None)
async def test_hdf_writer_fails_on_timeout_with_flyscan(
    patched_wait_for_value, RE: RunEngine, writer: HDFWriter
):
    controller = DummyController()
    set_sim_value(writer.hdf.file_path_exists, True)

    detector = StandardDetector(controller, writer)
    trigger_logic = DummyTriggerLogic()

    flyer = HardwareTriggeredFlyable(
        [detector], trigger_logic, [], name="flyer", trigger_to_frame_timeout=0.01
    )

    def flying_plan():
        """NOTE: the following is a workaround to ensure tests always pass.
        See https://github.com/bluesky/bluesky/issues/1630 for more details.
        """
        yield from bps.stage_all(flyer)
        try:
            yield from bps.open_run()
            yield from bps.kickoff(flyer)
            yield from bps.complete(flyer, wait=True)
            yield from bps.close_run()
        finally:
            yield from bps.unstage_all(flyer)

    RE(bps.prepare(flyer, 1))
    with pytest.raises(Exception) as exc:
        RE(flying_plan())

    assert isinstance(exc.value.__cause__, TimeoutError)
