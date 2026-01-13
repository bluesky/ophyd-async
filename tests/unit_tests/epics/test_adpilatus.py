from pathlib import Path
from unittest.mock import call, patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adpilatus


@pytest.fixture
async def test_adpilatus(
    static_path_provider: StaticPathProvider,
) -> adcore.AreaDetector[adpilatus.PilatusDriverIO]:
    async with init_devices(mock=True):
        detector = adpilatus.pilatus_detector("PREFIX:", static_path_provider)
    set_mock_value(detector.driver.armed, True)
    writer = detector.get_plugin("writer", adcore.NDFilePluginIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_adpilatus: adcore.AreaDetector[adpilatus.PilatusDriverIO]):
    assert test_adpilatus.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert test_adpilatus.driver.armed.source == "mock+ca://PREFIX:cam1:Armed"


@pytest.mark.parametrize(
    "readout_time",
    [adpilatus.PilatusReadoutTime.PILATUS2, adpilatus.PilatusReadoutTime.PILATUS3],
)
async def test_deadtime(readout_time: adpilatus.PilatusReadoutTime):
    path_provider = StaticPathProvider(StaticFilenameProvider("data"), Path("/tmp"))
    pilatus = adpilatus.pilatus_detector("PREFIX:", path_provider, readout_time)
    trigger_modes, deadtime = await pilatus.get_trigger_deadtime()
    assert trigger_modes == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    }
    assert deadtime == readout_time


async def test_times_out_if_not_armed(
    test_adpilatus: adcore.AreaDetector[adpilatus.PilatusDriverIO],
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
    test_adpilatus: adcore.AreaDetector[adpilatus.PilatusDriverIO],
):
    await test_adpilatus.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert list(get_mock(test_adpilatus.driver).mock_calls) == [
        call.trigger_mode.put(adpilatus.PilatusTriggerMode.EXT_TRIGGER, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(5, wait=True),
        call.acquire_time.put(0.5, wait=True),
        call.acquire.put(True, wait=True),
    ]


async def test_prepare_external_level(
    test_adpilatus: adcore.AreaDetector[adpilatus.PilatusDriverIO],
):
    await test_adpilatus.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            number_of_events=2,
        )
    )
    assert list(get_mock(test_adpilatus.driver).mock_calls) == [
        call.trigger_mode.put(adpilatus.PilatusTriggerMode.EXT_ENABLE, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(2, wait=True),
        call.acquire.put(True, wait=True),
    ]


async def test_prepare_forever(
    test_adpilatus: adcore.AreaDetector[adpilatus.PilatusDriverIO],
):
    await test_adpilatus.prepare(TriggerInfo(number_of_events=0))
    assert list(get_mock(test_adpilatus.driver).mock_calls) == [
        call.trigger_mode.put(adpilatus.PilatusTriggerMode.INTERNAL, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(999_999, wait=True),
    ]
