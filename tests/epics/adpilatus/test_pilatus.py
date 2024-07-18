from typing import Awaitable, Callable
from unittest.mock import patch

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (DetectorTrigger, DeviceCollector, PathProvider,
                              TriggerInfo, set_mock_value)
from ophyd_async.epics import adpilatus


@pytest.fixture
async def test_adpilatus(
    RE: RunEngine,
    static_path_provider: PathProvider,
) -> adpilatus.PilatusDetector:
    async with DeviceCollector(mock=True):
        test_adpilatus = adpilatus.PilatusDetector("PILATUS:", static_path_provider)

    return test_adpilatus


async def test_deadtime_overridable(static_path_provider: PathProvider):
    async with DeviceCollector(mock=True):
        test_adpilatus = adpilatus.PilatusDetector(
            "PILATUS:",
            static_path_provider,
            readout_time=adpilatus.PilatusReadoutTime.pilatus2,
        )
    pilatus_controller = test_adpilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 2.28e-3


async def test_deadtime_invariant(
    test_adpilatus: adpilatus.PilatusDetector,
):
    pilatus_controller = test_adpilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 0.95e-3
    assert pilatus_controller.get_deadtime(500) == 0.95e-3


@pytest.mark.parametrize(
    "detector_trigger,expected_trigger_mode",
    [
        (DetectorTrigger.internal, adpilatus.PilatusTriggerMode.internal),
        (DetectorTrigger.internal, adpilatus.PilatusTriggerMode.internal),
        (DetectorTrigger.internal, adpilatus.PilatusTriggerMode.internal),
    ],
)
async def test_trigger_mode_set(
    test_adpilatus: adpilatus.PilatusDetector,
    detector_trigger: DetectorTrigger,
    expected_trigger_mode: adpilatus.PilatusTriggerMode,
):
    async def trigger_and_complete():
        set_mock_value(test_adpilatus.drv.armed_for_triggers, True)
        status = await test_adpilatus.controller.arm(
            num=1,
            trigger=detector_trigger,
        )
        await status

    await _trigger(test_adpilatus, expected_trigger_mode, trigger_and_complete)


async def test_trigger_mode_set_without_armed_pv(test_adpilatus: adpilatus.PilatusDetector):
    async def trigger_and_complete():
        status = await test_adpilatus.controller.arm(
            num=1,
            trigger=DetectorTrigger.internal,
        )
        await status

    with patch(
        "ophyd_async.epics.adpilatus._pilatus_controller.DEFAULT_TIMEOUT",
        0.1,
    ):
        with pytest.raises(TimeoutError):
            await _trigger(test_adpilatus, adpilatus.PilatusTriggerMode.internal, trigger_and_complete)


async def _trigger(
    test_adpilatus: adpilatus.PilatusDetector,
    expected_trigger_mode: adpilatus.PilatusTriggerMode,
    trigger_and_complete: Callable[[], Awaitable],
):
    # Default TriggerMode
    assert (await test_adpilatus.drv.trigger_mode.get_value()) == adpilatus.PilatusTriggerMode.internal

    await trigger_and_complete()

    # TriggerSource changes
    assert (await test_adpilatus.drv.trigger_mode.get_value()) == expected_trigger_mode


async def test_hints_from_hdf_writer(test_adpilatus: adpilatus.PilatusDetector):
    assert test_adpilatus.hints == {"fields": ["test_adpilatus"]}


async def test_unsupported_trigger_excepts(test_adpilatus: adpilatus.PilatusDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"PilatusController only supports the following trigger types: .* but",
    ):
        await test_adpilatus.prepare(
            TriggerInfo(
                number=1,
                trigger=DetectorTrigger.edge_trigger,
                deadtime=1.0,
                livetime=1.0,
            )
        )


async def test_exposure_time_and_acquire_period_set(test_adpilatus: adpilatus.PilatusDetector):
    set_mock_value(test_adpilatus.drv.armed_for_triggers, True)
    await test_adpilatus.prepare(
        TriggerInfo(
            number=1, trigger=DetectorTrigger.internal, deadtime=1.0, livetime=1.0
        )
    )
    assert (await test_adpilatus.drv.acquire_time.get_value()) == 1.0
    assert (await test_adpilatus.drv.acquire_period.get_value()) == 1.0 + 950e-6
