import asyncio
from pathlib import Path
from typing import Any, Optional, Sequence
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
    ShapeProvider,
    StandardDetector,
    StandardFlyer,
    StaticDirectoryProvider,
    TriggerInfo,
    TriggerLogic,
    set_mock_value,
)
from ophyd_async.epics.adcore import ADBase, HDFWriter, NDFileHDF
from ophyd_async.epics.adsim import SimController


class DummyShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self) -> Sequence[int]:
        return (10, 10)


@pytest.fixture
async def hdf_writer(RE) -> HDFWriter:
    async with DeviceCollector(mock=True):
        hdf = NDFileHDF("HDF:")

    return HDFWriter(
        hdf,
        StaticDirectoryProvider("some_path", "some_prefix"),
        name_provider=lambda: "test",
        shape_provider=DummyShapeProvider(),
    )


async def test_correct_descriptor_doc_after_open(hdf_writer: HDFWriter):
    set_mock_value(hdf_writer.hdf.file_path_exists, True)
    with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer.open()

    assert descriptor == {
        "test": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "external": "STREAM:",
        }
    }

    await hdf_writer.close()


async def test_collect_stream_docs(hdf_writer: HDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file


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
def controller(RE) -> SimController:
    with DeviceCollector(mock=True):
        drv = ADBase("DRV")

    return SimController(drv)


@pytest.fixture
def writer(RE, tmp_path: Path) -> HDFWriter:
    with DeviceCollector(mock=True):
        hdf = NDFileHDF("HDF")

    return HDFWriter(
        hdf,
        directory_provider=StaticDirectoryProvider(tmp_path),
        name_provider=lambda: "test",
        shape_provider=AsyncMock(),
    )


@patch("ophyd_async.core._detector.DEFAULT_TIMEOUT", 0.1)
async def test_hdf_writer_fails_on_timeout_with_stepscan(
    RE: RunEngine,
    writer: HDFWriter,
    controller: SimController,
):
    set_mock_value(writer.hdf.file_path_exists, True)
    detector: StandardDetector[Any] = StandardDetector(
        controller, writer, name="detector"
    )

    with pytest.raises(Exception) as exc:
        RE(bp.count([detector]))

    assert isinstance(exc.value.__cause__, asyncio.TimeoutError)


@patch("ophyd_async.core._detector.DEFAULT_TIMEOUT", 0.1)
def test_hdf_writer_fails_on_timeout_with_flyscan(RE: RunEngine, writer: HDFWriter):
    controller = DummyController()
    set_mock_value(writer.hdf.file_path_exists, True)

    detector: StandardDetector[Optional[TriggerInfo]] = StandardDetector(
        controller, writer
    )
    trigger_logic = DummyTriggerLogic()

    flyer = StandardFlyer(trigger_logic, [], name="flyer")
    trigger_info = TriggerInfo(
        num=1, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
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
