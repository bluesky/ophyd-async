from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    OnOff,
    StaticPathProvider,
    TriggerInfo,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, advimba


@pytest.fixture
async def test_advimba(
    static_path_provider: StaticPathProvider,
) -> adcore.AreaDetector[advimba.VimbaDriverIO]:
    async with init_devices(mock=True):
        detector = advimba.vimba_detector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_advimba: adcore.AreaDetector[advimba.VimbaDriverIO]):
    assert test_advimba.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_advimba.driver.trigger_mode.source
        == "mock+ca://PREFIX:cam1:TriggerMode_RBV"
    )


@pytest.mark.parametrize(
    "model,deadtime", [("Mako G-125", 70e-6), ("Mako G-507", 554e-6)]
)
async def test_deadtime(
    test_advimba: adcore.AreaDetector[advimba.VimbaDriverIO],
    model: str,
    deadtime: float,
):
    # Set a default model for tests that need deadtime
    set_mock_value(test_advimba.driver.model, model)
    trigger_modes, actual_deadtime = await test_advimba.get_trigger_deadtime()
    assert trigger_modes == {
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_LEVEL,
        DetectorTrigger.EXTERNAL_EDGE,
    }
    assert deadtime == actual_deadtime


async def test_prepare_external_level(
    test_advimba: adcore.AreaDetector[advimba.VimbaDriverIO],
):
    await test_advimba.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            number_of_events=3,
        )
    )
    assert list(get_mock(test_advimba.driver).mock_calls) == [
        call.trigger_mode.put(OnOff.ON, wait=True),
        call.exposure_mode.put(advimba.VimbaExposeOutMode.TRIGGER_WIDTH, wait=True),
        call.trigger_source.put(advimba.VimbaTriggerSource.LINE1, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(3, wait=True),
        call.acquire.put(True, wait=True),
    ]


async def test_prepare_external_edge(
    test_advimba: adcore.AreaDetector[advimba.VimbaDriverIO],
):
    await test_advimba.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert list(get_mock(test_advimba.driver).mock_calls) == [
        call.trigger_mode.put(OnOff.ON, wait=True),
        call.exposure_mode.put(advimba.VimbaExposeOutMode.TIMED, wait=True),
        call.trigger_source.put(advimba.VimbaTriggerSource.LINE1, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(5, wait=True),
        call.acquire_time.put(0.5, wait=True),
        call.acquire.put(True, wait=True),
    ]


async def test_prepare_internal(
    test_advimba: adcore.AreaDetector[advimba.VimbaDriverIO],
):
    await test_advimba.prepare(TriggerInfo(number_of_events=11))
    assert list(get_mock(test_advimba.driver).mock_calls) == [
        call.trigger_mode.put(OnOff.OFF, wait=True),
        call.exposure_mode.put(advimba.VimbaExposeOutMode.TIMED, wait=True),
        call.trigger_source.put(advimba.VimbaTriggerSource.FREERUN, wait=True),
        call.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.num_images.put(11, wait=True),
    ]
