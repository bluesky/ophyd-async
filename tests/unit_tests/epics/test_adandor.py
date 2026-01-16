from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticPathProvider,
    TriggerInfo,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adandor, adcore


@pytest.fixture
async def test_adandor(
    static_path_provider: StaticPathProvider,
) -> adcore.AreaDetector[adandor.Andor2DriverIO]:
    async with init_devices(mock=True):
        detector = adandor.andor_detector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adandor: adcore.AreaDetector[adandor.Andor2DriverIO]):
    assert test_adandor.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_adandor.driver.andor_accumulate_period.source
        == "mock+ca://PREFIX:cam1:AndorAccumulatePeriod_RBV"
    )


async def test_deadtime(
    test_adandor: adcore.AreaDetector[adandor.Andor2DriverIO],
):
    trigger_modes, deadtime = await test_adandor.get_trigger_deadtime()
    assert trigger_modes == {DetectorTrigger.INTERNAL, DetectorTrigger.EXTERNAL_EDGE}
    assert deadtime == 0.1


async def test_prepare_external_edge(
    test_adandor: adcore.AreaDetector[adandor.Andor2DriverIO],
):
    await test_adandor.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert list(get_mock(test_adandor.driver).mock_calls) == [
        call.trigger_mode.put(adandor.Andor2TriggerMode.EXT_TRIGGER, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(5, wait=True),
        call.acquire_time.put(0.5, wait=True),
        call.acquire.put(True, wait=True),
    ]


async def test_prepare_forever(
    test_adandor: adcore.AreaDetector[adandor.Andor2DriverIO],
):
    await test_adandor.prepare(TriggerInfo(number_of_events=0))
    assert list(get_mock(test_adandor.driver).mock_calls) == [
        call.trigger_mode.put(adandor.Andor2TriggerMode.INTERNAL, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(999_999, wait=True),
    ]
