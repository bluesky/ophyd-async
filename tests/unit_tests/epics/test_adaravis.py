from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    OnOff,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adaravis, adcore
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_adaravis(
    static_path_provider: StaticPathProvider,
) -> adaravis.AravisDetector:
    async with init_devices(mock=True):
        detector = adaravis.AravisDetector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adaravis: adaravis.AravisDetector):
    assert test_adaravis.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_adaravis.driver.trigger_mode.source
        == "mock+ca://PREFIX:cam1:TriggerMode_RBV"
    )


@pytest.mark.parametrize(
    "model,deadtime", [("Mako G-125", 70e-6), ("Mako G-507", 554e-6)]
)
async def test_deadtime(
    test_adaravis: adaravis.AravisDetector,
    model: str,
    deadtime: float,
):
    # Set a default model for tests that need deadtime
    set_mock_value(test_adaravis.driver.model, model)
    trigger_modes, actual_deadtime = await test_adaravis.get_trigger_deadtime()
    assert trigger_modes == {DetectorTrigger.INTERNAL, DetectorTrigger.EXTERNAL_EDGE}
    assert deadtime == actual_deadtime


async def test_prepare_external_edge(
    test_adaravis: adaravis.AravisDetector,
):
    await test_adaravis.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_adaravis.driver,
        [
            call.trigger_mode.put(OnOff.ON),
            call.trigger_source.put(adaravis.AravisTriggerSource.LINE1),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(5),
            call.acquire_time.put(0.5),
            call.acquire.put(True),
        ],
    )


async def test_prepare_internal(
    test_adaravis: adaravis.AravisDetector,
):
    await test_adaravis.prepare(TriggerInfo(number_of_events=11))
    assert_has_calls(
        test_adaravis.driver,
        [
            call.trigger_mode.put(OnOff.OFF),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(11),
        ],
    )


@pytest.mark.parametrize("num_images,expected_first_dim", [(5, 5), (0, 1)])
async def test_trigger_uses_num_images(
    test_adaravis: adaravis.AravisDetector,
    monkeypatch: pytest.MonkeyPatch,
    num_images: int,
    expected_first_dim: int,
):
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    detector = test_adaravis
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
