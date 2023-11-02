import asyncio
from unittest.mock import AsyncMock, Mock, patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    AsyncStatus,
    DetectorTrigger,
    DeviceCollector,
    DirectoryInfo,
    StandardDetector,
    TriggerInfo,
    TriggerLogic,
    set_sim_value,
)
from ophyd_async.core.flyer import (
    HardwareTriggeredFlyable,
    SameTriggerDetectorGroupLogic,
)
from ophyd_async.epics.areadetector.controllers import ADSimController
from ophyd_async.epics.areadetector.drivers import ADBase
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self):
        ...

    def trigger_info(self, value: int) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
        )

    async def prepare(self, value: int):
        return value

    async def start(self):
        ...

    async def stop(self):
        ...


@pytest.fixture
def controller() -> ADSimController:
    with DeviceCollector(sim=True):
        drv = ADBase("DRV")

    return ADSimController(drv)


@pytest.fixture
def writer() -> HDFWriter:
    with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF")

    return HDFWriter(
        hdf,
        directory_provider=Mock(return_value=DirectoryInfo("somepath", "someprefix")),
        name_provider=lambda: "test",
        shape_provider=AsyncMock(),
    )


@patch("ophyd_async.core.detector.DEFAULT_TIMEOUT", 0.1)
async def test_hdf_writer_fails_on_timeout_with_stepscan(
    RE: RunEngine, writer: HDFWriter, controller: ADSimController
):
    set_sim_value(writer.hdf.file_path_exists, True)
    detector = StandardDetector(controller, writer, name="detector")

    with pytest.raises(Exception) as exc:
        RE(bp.count([detector]))

    assert isinstance(exc.value.__cause__, TimeoutError)




async def test_hdf_writer_fails_on_timeout_with_flyscan(
    RE: RunEngine, writer: HDFWriter, controller: ADSimController
):
    set_sim_value(writer.hdf.file_path_exists, True)
    controller.arm = AsyncMock(return_value=AsyncStatus(asyncio.sleep(0.01)))  # type: ignore
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    trigger_logic = DummyTriggerLogic()
    detector_group = SameTriggerDetectorGroupLogic([controller], [writer])
    flyer = HardwareTriggeredFlyable(
        detector_group, trigger_logic, [], name="flyer", timeout=0.1
    )

    def flying_plan():
        yield from bps.stage_all(flyer)
        yield from bps.open_run()
        yield from bps.kickoff(flyer)
        yield from bps.complete(flyer, wait=False, group="complete")

        done = False
        while not done:
            try:
                yield from bps.wait(group="complete", timeout=0.5)
            except TimeoutError:
                pass
            else:
                done = True

            yield from bps.collect(
                flyer, stream=True, return_payload=False, name="primary"
            )
            yield from bps.sleep(0.001)
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer)

    RE(bps.mv(flyer, 1))
    with pytest.raises(Exception) as exc:
        RE(flying_plan())

    assert isinstance(exc.value.__cause__, TimeoutError)
