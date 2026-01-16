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
from ophyd_async.epics import adcore, adsimdetector


@pytest.fixture
async def test_adsimdetector(
    static_path_provider: StaticPathProvider,
) -> adsimdetector.SimDetector:
    async with init_devices(mock=True):
        detector = adsimdetector.SimDetector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adsimdetector: adsimdetector.SimDetector):
    assert (
        test_adsimdetector.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    )


async def test_deadtime(
    test_adsimdetector: adsimdetector.SimDetector,
):
    trigger_modes, actual_deadtime = await test_adsimdetector.get_trigger_deadtime()
    assert trigger_modes == {DetectorTrigger.INTERNAL}
    assert actual_deadtime is None


async def test_prepare_internal(
    test_adsimdetector: adsimdetector.SimDetector,
):
    await test_adsimdetector.prepare(TriggerInfo(number_of_events=11))
    assert list(get_mock(test_adsimdetector.driver).mock_calls) == [
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(11, wait=True),
    ]
