from unittest.mock import call

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    OnOff,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, advimba
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def test_advimba(
    static_path_provider: StaticPathProvider,
) -> advimba.VimbaDetector:
    async with init_devices(mock=True):
        detector = advimba.VimbaDetector("PREFIX:", static_path_provider)
    writer = detector.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    return detector


def test_pvs_correct(test_advimba: advimba.VimbaDetector):
    assert test_advimba.driver.acquire.source == "mock+ca://PREFIX:cam1:Acquire_RBV"
    assert (
        test_advimba.driver.trigger_mode.source
        == "mock+ca://PREFIX:cam1:TriggerMode_RBV"
    )


@pytest.mark.parametrize(
    "model,deadtime", [("Mako G-125", 70e-6), ("Mako G-507", 554e-6)]
)
async def test_deadtime(
    test_advimba: advimba.VimbaDetector,
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
    test_advimba: advimba.VimbaDetector,
):
    await test_advimba.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_LEVEL,
            number_of_events=3,
        )
    )
    assert_has_calls(
        test_advimba.driver,
        [
            call.trigger_mode.put(OnOff.ON),
            call.exposure_mode.put(advimba.VimbaExposeOutMode.TRIGGER_WIDTH),
            call.trigger_source.put(advimba.VimbaTriggerSource.LINE1),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(3),
            call.acquire.put(True),
        ],
    )


async def test_prepare_external_edge(
    test_advimba: advimba.VimbaDetector,
):
    await test_advimba.prepare(
        TriggerInfo(
            trigger=DetectorTrigger.EXTERNAL_EDGE,
            number_of_events=5,
            livetime=0.5,
        )
    )
    assert_has_calls(
        test_advimba.driver,
        [
            call.trigger_mode.put(OnOff.ON),
            call.exposure_mode.put(advimba.VimbaExposeOutMode.TIMED),
            call.trigger_source.put(advimba.VimbaTriggerSource.LINE1),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(5),
            call.acquire_time.put(0.5),
            call.acquire.put(True),
        ],
    )


async def test_prepare_internal(
    test_advimba: advimba.VimbaDetector,
):
    await test_advimba.prepare(TriggerInfo(number_of_events=11))
    assert_has_calls(
        test_advimba.driver,
        [
            call.trigger_mode.put(OnOff.OFF),
            call.exposure_mode.put(advimba.VimbaExposeOutMode.TIMED),
            call.trigger_source.put(advimba.VimbaTriggerSource.FREERUN),
            call.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.num_images.put(11),
        ],
    )
