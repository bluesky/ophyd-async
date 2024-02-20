import asyncio
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    DeviceCollector,
    DirectoryInfo,
    HardwareTriggeredFlyable,
    StandardDetector,
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
def writer(RE) -> HDFWriter:
    with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF")

    return HDFWriter(
        hdf,
        directory_provider=Mock(return_value=DirectoryInfo("somepath", "someprefix")),
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


# Look at this
@patch("ophyd_async.epics.areadetector.utils.wait_for_value", return_value=None)
def test_hdf_writer_fails_on_timeout_with_flyscan(
    patched_wait_for_value, RE: RunEngine, writer: HDFWriter
):
    controller = DummyController()
    set_sim_value(writer.hdf.file_path_exists, True)

    detector = StandardDetector(controller, writer, trigger_to_frame_timeout=0.01)
    trigger_logic = DummyTriggerLogic()

    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")

    def flying_plan():
        """NOTE: the following is a workaround to ensure tests always pass.
        See https://github.com/bluesky/bluesky/issues/1630 for more details.
        """
        yield from bps.stage_all(detector, flyer)
        try:
            # Prepare the flyer first to get the trigger info for the detectors
            yield from bps.prepare(flyer, 1, wait=True)
            # prepare detector second.
            yield from bps.prepare(
                detector, flyer.trigger_info, wait=True, current_frame=0, last_frame=10
            )

            yield from bps.open_run()
            yield from bps.kickoff(flyer)
            yield from bps.kickoff(detector)
            yield from bps.complete(flyer, wait=True)
            yield from bps.complete(detector, wait=True)
            yield from bps.close_run()
        finally:
            yield from bps.unstage_all(detector, flyer)

    with pytest.raises(TimeoutError) as exc:
        RE(flying_plan())

    assert isinstance(exc.value.__cause__, TimeoutError)
