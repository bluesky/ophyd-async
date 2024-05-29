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
from ophyd_async.epics.areadetector.pilatus import PilatusDetector


@pytest.fixture
async def pilatus(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> PilatusDetector:
    async with DeviceCollector(mock=True):
        adpilatus = PilatusDetector("PILATUS:", static_directory_provider)

    return adpilatus


async def test_deadtime_invariant(
    pilatus: PilatusDetector,
):
    pilatus_controller = pilatus.controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 2.28e-3
    assert pilatus_controller.get_deadtime(500) == 2.28e-3


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
        status = await pilatus.controller.arm(num=1, trigger=detector_trigger)
        # Prevent timeouts
        set_mock_value(pilatus.drv.acquire, True)
        set_mock_value(pilatus.drv.armed_for_triggers, True)
        await status

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
        await pilatus.prepare(TriggerInfo(1, DetectorTrigger.edge_trigger, 1, 1))
