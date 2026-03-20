from unittest.mock import call, patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adpilatus
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_adpilatus(
    static_path_provider: StaticPathProvider,
) -> adpilatus.PilatusDetector:
    async with init_devices(mock=True):
        detector = adpilatus.PilatusDetector("PREFIX:", static_path_provider)
    set_mock_value(detector.driver.armed, True)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adpilatus: adpilatus.PilatusDetector):
    assert test_adpilatus.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert test_adpilatus.driver.armed.source == "mock+ca://PREFIX:cam1:Armed"


@pytest.mark.parametrize(
    "readout_time",
    [adpilatus.PilatusReadoutTime.PILATUS2, adpilatus.PilatusReadoutTime.PILATUS3],
)
async def test_deadtime(readout_time: adpilatus.PilatusReadoutTime, tmp_path):
    path_provider = StaticPathProvider(StaticFilenameProvider("data"), tmp_path)
    pilatus = adpilatus.PilatusDetector("PREFIX:", path_provider, readout_time)
    trigger_modes, deadtime = await pilatus.get_trigger_deadtime()
    assert trigger_modes == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    }
    assert deadtime == readout_time


async def test_times_out_if_not_armed(
    test_adpilatus: adpilatus.PilatusDetector,
):
    set_mock_value(test_adpilatus.driver.armed, False)
    with patch(
        "ophyd_async.epics.adcore._arm_logic.DEFAULT_TIMEOUT",
        0.01,
    ):
        with pytest.raises(TimeoutError):
            await test_adpilatus.prepare(
                TriggerInfo(trigger=DetectorTrigger.EXTERNAL_EDGE)
            )


async def test_prepare_external_edge(
    test_adpilatus: adpilatus.PilatusDetector,
):
    await test_adpilatus.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_adpilatus.driver,
        [
            call.trigger_mode.put(adpilatus.PilatusTriggerMode.EXT_TRIGGER),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(5),
            call.acquire_time.put(0.5),
            call.acquire.put(True),
        ],
    )


async def test_prepare_external_level(
    test_adpilatus: adpilatus.PilatusDetector,
):
    await test_adpilatus.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            number_of_events=2,
        )
    )
    assert_has_calls(
        test_adpilatus.driver,
        [
            call.trigger_mode.put(adpilatus.PilatusTriggerMode.EXT_ENABLE),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(2),
            call.acquire.put(True),
        ],
    )


async def test_prepare_forever(
    test_adpilatus: adpilatus.PilatusDetector,
):
    await test_adpilatus.prepare(TriggerInfo(number_of_events=0))
    assert_has_calls(
        test_adpilatus.driver,
        [
            call.trigger_mode.put(adpilatus.PilatusTriggerMode.INTERNAL),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(999_999),
        ],
    )


@pytest.mark.parametrize("num_images,expected_first_dim", [(7, 7), (0, 1)])
async def test_trigger_uses_num_images(
    test_adpilatus: adpilatus.PilatusDetector,
    monkeypatch: pytest.MonkeyPatch,
    num_images: int,
    expected_first_dim: int,
):
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    detector = test_adpilatus
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
