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
from ophyd_async.epics import adandor3, adcore
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_adandor3(
    static_path_provider: StaticPathProvider,
) -> adandor3.Andor3Detector:
    async with init_devices(mock=True):
        detector = adandor3.Andor3Detector(
            "PREFIX:", adcore.ADWriterFactory.hdf(static_path_provider)
        )
    writer = detector.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


async def test_deadtime(
    test_adandor3: adandor3.Andor3Detector,
):
    trigger_modes, deadtime = await test_adandor3.get_trigger_deadtime()
    assert trigger_modes == {DetectorTrigger.INTERNAL, DetectorTrigger.EXTERNAL_EDGE}
    assert deadtime == 0.1


async def test_prepare_external_edge(
    test_adandor3: adandor3.Andor3Detector,
):
    await test_adandor3.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_adandor3.driver,
        [
            call.trigger_mode.put(adandor3.Andor3TriggerMode.EXT_TRIGGER),
            call.image_mode.put(adandor3.Andor3ImageMode.FIXED),
            call.num_images.put(5),
            call.acquire_time.put(0.5),
            call.acquire.put(True),
        ],
    )


async def test_prepare_forever(
    test_adandor3: adandor3.Andor3Detector,
):
    await test_adandor3.prepare(TriggerInfo(number_of_events=0))
    assert_has_calls(
        test_adandor3.driver,
        [
            call.trigger_mode.put(adandor3.Andor3TriggerMode.INTERNAL),
            call.image_mode.put(adandor3.Andor3ImageMode.FIXED),
            call.num_images.put(999_999),
        ],
    )


@pytest.mark.parametrize("num_images,expected_first_dim", [(3, 3), (0, 1)])
async def test_trigger_uses_num_images(
    test_adandor3: adandor3.Andor3Detector,
    monkeypatch: pytest.MonkeyPatch,
    num_images: int,
    expected_first_dim: int,
):
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    detector = test_adandor3
    writer = detector.get_plugin("hdf", adcore.NDFileHDF5IO)
    set_mock_value(detector.driver.num_images, num_images)
    await detector.stage()
    callback_on_mock_put(
        detector.driver.acquire,
        lambda v: set_mock_value(writer.num_captured, expected_first_dim),
    )
    await detector.trigger()
    description = await detector.describe()
    assert description["detector"]["shape"][0] == expected_first_dim
