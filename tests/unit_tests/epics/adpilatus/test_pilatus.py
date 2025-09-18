import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adcore
from ophyd_async.epics.adpilatus import (
    PilatusDetector,
    PilatusDriverIO,
    PilatusReadoutTime,
    PilatusTriggerMode,
)
from ophyd_async.testing import set_mock_value


@pytest.fixture
def test_adpilatus(ad_standard_det_factory) -> PilatusDetector:
    return ad_standard_det_factory(PilatusDetector)


@pytest.mark.parametrize(
    "readout_time",
    [PilatusReadoutTime.PILATUS2, PilatusReadoutTime.PILATUS3],
)
async def test_given_a_different_readout_time_then_deadtime_is_changed(
    ad_standard_det_factory, readout_time: float
):
    detector: PilatusDetector = ad_standard_det_factory(
        PilatusDetector, readout_time=readout_time
    )
    assert detector._controller.get_deadtime(None) == readout_time


async def test_deadtime_invariant(
    test_adpilatus: PilatusDetector,
):
    pilatus_controller = test_adpilatus._controller
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 0.95e-3
    assert pilatus_controller.get_deadtime(500) == 0.95e-3


@pytest.mark.parametrize(
    "detector_trigger,expected_trigger_mode",
    [
        (DetectorTrigger.INTERNAL, PilatusTriggerMode.INTERNAL),
        (DetectorTrigger.CONSTANT_GATE, PilatusTriggerMode.EXT_ENABLE),
        (DetectorTrigger.VARIABLE_GATE, PilatusTriggerMode.EXT_ENABLE),
        (DetectorTrigger.EDGE_TRIGGER, PilatusTriggerMode.EXT_TRIGGER),
    ],
)
async def test_trigger_mode_set(
    test_adpilatus: PilatusDetector,
    detector_trigger: DetectorTrigger,
    expected_trigger_mode: PilatusTriggerMode,
):
    async def trigger_and_complete():
        set_mock_value(test_adpilatus.driver.armed, True)
        await test_adpilatus._controller.prepare(
            TriggerInfo(number_of_events=1, trigger=detector_trigger)
        )
        await test_adpilatus._controller.arm()
        await test_adpilatus._controller.wait_for_idle()

    await _trigger(test_adpilatus, expected_trigger_mode, trigger_and_complete)


async def test_trigger_mode_set_without_armed_pv(
    test_adpilatus: PilatusDetector,
):
    async def trigger_and_complete():
        await test_adpilatus._controller.prepare(
            TriggerInfo(number_of_events=1, trigger=DetectorTrigger.INTERNAL)
        )
        await test_adpilatus._controller.arm()
        await test_adpilatus._controller.wait_for_idle()

    with patch(
        "ophyd_async.epics.adpilatus._pilatus_controller.DEFAULT_TIMEOUT",
        0.1,
    ):
        with pytest.raises(asyncio.TimeoutError):
            await _trigger(
                test_adpilatus,
                PilatusTriggerMode.INTERNAL,
                trigger_and_complete,
            )


async def _trigger(
    test_adpilatus: PilatusDetector,
    expected_trigger_mode: PilatusTriggerMode,
    trigger_and_complete: Callable[[], Awaitable],
):
    pilatus_driver = test_adpilatus.driver
    # Default TriggerMode
    assert await pilatus_driver.trigger_mode.get_value() == PilatusTriggerMode.INTERNAL

    await trigger_and_complete()

    # TriggerSource changes
    assert (await pilatus_driver.trigger_mode.get_value()) == expected_trigger_mode


async def test_exposure_time_and_acquire_period_set(
    test_adpilatus: PilatusDetector,
):
    async def dummy_open(name: str, exposures_per_event: int = 1):
        test_adpilatus._writer._exposures_per_event = exposures_per_event
        return {}

    test_adpilatus._writer.open = dummy_open
    set_mock_value(test_adpilatus.driver.armed, True)
    await test_adpilatus.prepare(
        TriggerInfo(
            number_of_events=1,
            trigger=DetectorTrigger.INTERNAL,
            deadtime=1.0,
            livetime=1.0,
        )
    )
    assert (await test_adpilatus.driver.acquire_time.get_value()) == 1.0
    assert (await test_adpilatus.driver.acquire_period.get_value()) == 1.0 + 950e-6


async def test_pilatus_controller(test_adpilatus: PilatusDetector):
    pilatus = test_adpilatus._controller
    pilatus_driver = cast(PilatusDriverIO, test_adpilatus.driver)
    set_mock_value(pilatus_driver.armed, True)
    await pilatus.prepare(
        TriggerInfo(number_of_events=1, trigger=DetectorTrigger.CONSTANT_GATE)
    )
    await pilatus.arm()
    await pilatus.wait_for_idle()

    assert await pilatus_driver.num_images.get_value() == 1
    assert await pilatus_driver.image_mode.get_value() == adcore.ADImageMode.MULTIPLE
    assert (
        await pilatus_driver.trigger_mode.get_value() == PilatusTriggerMode.EXT_ENABLE
    )

    assert await pilatus_driver.acquire.get_value() is True

    await pilatus.disarm()

    assert await pilatus_driver.acquire.get_value() is False
