from typing import Awaitable, Callable
from unittest.mock import patch

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (DetectorTrigger, DeviceCollector,
                              DirectoryProvider, TriggerInfo, set_mock_value)
from ophyd_async.epics import adpilatus


@pytest.fixture
async def mock_pilatus(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> adpilatus.PilatusDetector:
    async with DeviceCollector(mock=True):
        mock_pilatus = adpilatus.PilatusDetector("PILATUS:", static_directory_provider)

    return mock_pilatus


async def test_deadtime_overridable(static_directory_provider: DirectoryProvider):
    async with DeviceCollector(mock=True):
        test_pilatus = adpilatus.PilatusDetector(
            "PILATUS:",
            static_directory_provider,
            readout_time=adpilatus.PilatusReadoutTime.pilatus2,
        )
    pilatus_controller = test_pilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 2.28e-3


async def test_deadtime_invariant(
    mock_pilatus: adpilatus.PilatusDetector,
):
    pilatus_controller = mock_pilatus.controller
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
    mock_pilatus: adpilatus.PilatusDetector,
    detector_trigger: DetectorTrigger,
    expected_trigger_mode: adpilatus.PilatusTriggerMode,
):
    async def trigger_and_complete():
        set_mock_value(mock_pilatus.drv.armed_for_triggers, True)
        status = await mock_pilatus.controller.arm(
            num=1,
            trigger=detector_trigger,
        )
        await status

    await _trigger(mock_pilatus, expected_trigger_mode, trigger_and_complete)


async def test_trigger_mode_set_without_armed_pv(mock_pilatus: adpilatus.PilatusDetector):
    async def trigger_and_complete():
        status = await mock_pilatus.controller.arm(
            num=1,
            trigger=DetectorTrigger.internal,
        )
        await status

    with patch(
        "ophyd_async.epics.adpilatus._pilatus_controller.DEFAULT_TIMEOUT",
        0.1,
    ):
        with pytest.raises(TimeoutError):
            await _trigger(mock_pilatus, adpilatus.PilatusTriggerMode.internal, trigger_and_complete)


async def _trigger(
    mock_pilatus: adpilatus.PilatusDetector,
    expected_trigger_mode: adpilatus.PilatusTriggerMode,
    trigger_and_complete: Callable[[], Awaitable],
):
    # Default TriggerMode
    assert (await mock_pilatus.drv.trigger_mode.get_value()) == adpilatus.PilatusTriggerMode.internal

    await trigger_and_complete()

    # TriggerSource changes
    assert (await mock_pilatus.drv.trigger_mode.get_value()) == expected_trigger_mode


async def test_hints_from_hdf_writer(mock_pilatus: adpilatus.PilatusDetector):
    assert mock_pilatus.hints == {"fields": ["adpilatus"]}


async def test_unsupported_trigger_excepts(mock_pilatus: adpilatus.PilatusDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"PilatusController only supports the following trigger types: .* but",
    ):
        await mock_pilatus.prepare(TriggerInfo(1, DetectorTrigger.edge_trigger, 1, 1))
