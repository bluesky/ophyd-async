from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adkinetix
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_adkinetix(
    static_path_provider: StaticPathProvider,
) -> adkinetix.KinetixDetector:
    async with init_devices(mock=True):
        detector = adkinetix.KinetixDetector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adkinetix: adkinetix.KinetixDetector):
    assert test_adkinetix.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_adkinetix.driver.readout_port_idx.source
        == "mock+ca://PREFIX:cam1:ReadoutPortIdx"
    )


async def test_deadtime(
    test_adkinetix: adkinetix.KinetixDetector,
):
    trigger_modes, deadtime = await test_adkinetix.get_trigger_deadtime()
    assert trigger_modes == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    }
    assert deadtime == 0.001


async def test_prepare_external_edge(
    test_adkinetix: adkinetix.KinetixDetector,
):
    await test_adkinetix.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_adkinetix.driver,
        [
            call.trigger_mode.put(adkinetix.KinetixTriggerMode.EDGE, wait=True),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
            call.num_images.put(5, wait=True),
            call.acquire_time.put(0.5, wait=True),
            call.acquire.put(True, wait=True),
        ],
    )


async def test_prepare_external_level(
    test_adkinetix: adkinetix.KinetixDetector,
):
    await test_adkinetix.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            number_of_events=2,
        )
    )
    assert_has_calls(
        test_adkinetix.driver,
        [
            call.trigger_mode.put(adkinetix.KinetixTriggerMode.GATE, wait=True),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
            call.num_images.put(2, wait=True),
            call.acquire.put(True, wait=True),
        ],
    )


async def test_prepare_internal(
    test_adkinetix: adkinetix.KinetixDetector,
):
    await test_adkinetix.prepare(TriggerInfo(number_of_events=2, livetime=0.3))
    assert_has_calls(
        test_adkinetix.driver,
        [
            call.trigger_mode.put(adkinetix.KinetixTriggerMode.INTERNAL, wait=True),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
            call.num_images.put(2, wait=True),
            call.acquire_time.put(0.3, wait=True),
        ],
    )
