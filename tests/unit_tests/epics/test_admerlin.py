from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, admerlin
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_admerlin(
    static_path_provider: StaticPathProvider,
) -> admerlin.MerlinDetector:
    async with init_devices(mock=True):
        detector = admerlin.MerlinDetector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_admerlin: admerlin.MerlinDetector):
    assert test_admerlin.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_admerlin.driver.trigger_mode.source
        == "mock+ca://PREFIX:cam1:TriggerMode_RBV"
    )


async def test_deadtime(
    test_admerlin: admerlin.MerlinDetector,
):
    trigger_modes, deadtime = await test_admerlin.get_trigger_deadtime()
    assert trigger_modes == {DetectorTrigger.INTERNAL, DetectorTrigger.EXTERNAL_EDGE}
    assert deadtime == 0.002


async def test_prepare_external_edge(
    test_admerlin: admerlin.MerlinDetector,
):
    await test_admerlin.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_admerlin.driver,
        [
            call.trigger_mode.put(admerlin.MerlinTriggerMode.TRIGGER_START_RISING),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(5),
            call.acquire_time.put(0.5),
            call.acquire.put(True),
        ],
    )


@pytest.mark.parametrize("num_images,expected_first_dim", [(8, 8), (0, 1)])
async def test_trigger_uses_num_images(
    test_admerlin: admerlin.MerlinDetector,
    monkeypatch: pytest.MonkeyPatch,
    num_images: int,
    expected_first_dim: int,
):
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    detector = test_admerlin
    writer = detector.get_plugin("writer", adcore.NDFileHDF5IO)
    set_mock_value(detector.driver.num_images, num_images)
    await detector.stage()
    callback_on_mock_put(
        detector.driver.acquire,
        lambda v: set_mock_value(writer.num_captured, expected_first_dim),
    )
    await detector.trigger()
    description = await detector.describe()
    assert description["detector"]["shape"][0] == expected_first_dim
