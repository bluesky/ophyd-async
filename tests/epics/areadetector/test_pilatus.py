from typing import Awaitable, Callable
from unittest.mock import patch

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    TriggerInfo,
    set_mock_value,
)
from ophyd_async.epics.areadetector.drivers.pilatus_driver import PilatusTriggerMode
from ophyd_async.epics.areadetector.pilatus import PilatusDetector, PilatusReadoutTime


@pytest.fixture
async def pilatus(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> PilatusDetector:
    async with DeviceCollector(mock=True):
        adpilatus = PilatusDetector("PILATUS:", static_directory_provider)

    return adpilatus


async def test_deadtime_overridable(static_directory_provider: DirectoryProvider):
    async with DeviceCollector(mock=True):
        pilatus = PilatusDetector(
            "PILATUS:",
            static_directory_provider,
            readout_time=PilatusReadoutTime.pilatus2,
        )
    pilatus_controller = pilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 2.28e-3


async def test_deadtime_invariant(
    pilatus: PilatusDetector,
):
    pilatus_controller = pilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 0.95e-3
    assert pilatus_controller.get_deadtime(500) == 0.95e-3


@pytest.mark.parametrize(
    "detector_trigger,expected_trigger_mode",
    [
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
    ],
)
async def test_trigger_mode_set(
    pilatus: PilatusDetector,
    detector_trigger: DetectorTrigger,
    expected_trigger_mode: PilatusTriggerMode,
):
    async def trigger_and_complete():
        set_mock_value(pilatus.drv.armed_for_triggers, True)
        status = await pilatus.controller.arm(
            num=1,
            trigger=detector_trigger,
        )
        await status

    await _trigger(pilatus, expected_trigger_mode, trigger_and_complete)


async def test_trigger_mode_set_without_armed_pv(pilatus: PilatusDetector):
    async def trigger_and_complete():
        status = await pilatus.controller.arm(
            num=1,
            trigger=DetectorTrigger.internal,
        )
        await status

    with patch(
        "ophyd_async.epics.areadetector.controllers.pilatus_controller.DEFAULT_TIMEOUT",
        0.1,
    ):
        with pytest.raises(TimeoutError):
            await _trigger(pilatus, PilatusTriggerMode.internal, trigger_and_complete)


async def _trigger(
    pilatus: PilatusDetector,
    expected_trigger_mode: PilatusTriggerMode,
    trigger_and_complete: Callable[[], Awaitable],
):
    # Default TriggerMode
    assert (await pilatus.drv.trigger_mode.get_value()) == PilatusTriggerMode.internal

    await trigger_and_complete()

    # TriggerSource changes
    assert (await pilatus.drv.trigger_mode.get_value()) == expected_trigger_mode


async def test_hints_from_hdf_writer(pilatus: PilatusDetector):
    assert pilatus.hints == {"fields": ["adpilatus"]}


async def test_unsupported_trigger_excepts(pilatus: PilatusDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"PilatusController only supports the following trigger types: .* but",
    ):
        await pilatus.prepare(TriggerInfo(1, DetectorTrigger.edge_trigger, 1.0, 1.0))


async def test_exposure_time_and_acquire_period_set(pilatus: PilatusDetector):
    set_mock_value(pilatus.drv.armed_for_triggers, True)
    await pilatus.prepare(TriggerInfo(1, DetectorTrigger.internal, 1.0, 1.0))
    assert (await pilatus.drv.acquire_time.get_value()) == 1.0
    assert (await pilatus.drv.acquire_period.get_value()) == 1.0 + 950e-6
