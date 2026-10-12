import pytest

from ophyd_async.core import (
    DetectorTrigger,
    OnOff,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import (
    adandor,
    adaravis,
    adcore,
    adkinetix,
    admerlin,
    adpilatus,
    adsimdetector,
    advimba,
)

# driver_class, trigger_logic_class, extra_args, mode_settings
_TRIGGER_LOGIC_CASES = [
    pytest.param(
        adcore.ADBaseIO,
        adsimdetector.SimDetectorTriggerLogic,
        (None,),
        {},
        id="sim",
    ),
    pytest.param(
        adandor.Andor2DriverIO,
        adandor.Andor2TriggerLogic,
        (None,),
        {"trigger_mode": adandor.Andor2TriggerMode.EXT_TRIGGER},
        id="andor2",
    ),
    pytest.param(
        adaravis.AravisDriverIO,
        adaravis.AravisTriggerLogic,
        (None,),
        {"trigger_mode": OnOff.ON},
        id="aravis",
    ),
    pytest.param(
        adkinetix.KinetixDriverIO,
        adkinetix.KinetixTriggerLogic,
        (None,),
        {"trigger_mode": adkinetix.KinetixTriggerMode.GATE},
        id="kinetix",
    ),
    pytest.param(
        admerlin.MerlinDriverIO,
        admerlin.MerlinTriggerLogic,
        (None,),
        {"trigger_mode": admerlin.MerlinTriggerMode.SOFTWARE},
        id="merlin",
    ),
    pytest.param(
        adpilatus.PilatusDriverIO,
        adpilatus.PilatusTriggerLogic,
        (adpilatus.PilatusReadoutTime.PILATUS3, None),
        {"trigger_mode": adpilatus.PilatusTriggerMode.EXT_ENABLE},
        id="pilatus",
    ),
    pytest.param(
        advimba.VimbaDriverIO,
        advimba.VimbaTriggerLogic,
        (None,),
        {
            "trigger_mode": OnOff.ON,
            "exposure_mode": advimba.VimbaExposeOutMode.TRIGGER_WIDTH,
        },
        id="vimba",
    ),
]


@pytest.mark.parametrize(
    "driver_class, trigger_logic_class, extra_args, mode_settings",
    _TRIGGER_LOGIC_CASES,
)
async def test_default_trigger_info_is_internal_regardless_of_trigger_mode(
    driver_class, trigger_logic_class, extra_args, mode_settings
):
    async with init_devices(mock=True):
        driver = driver_class("PREFIX:")
    for name, value in mode_settings.items():
        set_mock_value(getattr(driver, name), value)
    set_mock_value(driver.num_images, 5)

    trigger_logic = trigger_logic_class(driver, *extra_args)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.trigger == DetectorTrigger.INTERNAL
    assert trigger_info.collections_per_event == 5
    assert trigger_info.exposures_per_collection == 1


@pytest.mark.parametrize(
    "num_images, expected_collections_per_event",
    [(1, 1), (5, 5), (0, 1)],
)
async def test_default_trigger_info_uses_num_images_without_process_plugin(
    num_images, expected_collections_per_event
):
    async with init_devices(mock=True):
        driver = adcore.ADBaseIO("PREFIX:")
    set_mock_value(driver.num_images, num_images)

    trigger_logic = adsimdetector.SimDetectorTriggerLogic(driver, None)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.collections_per_event == expected_collections_per_event
    assert trigger_info.exposures_per_collection == 1


@pytest.mark.parametrize(
    "num_images, num_filter, enable_filter, expected_collections, expected_exposures",
    [
        (10, 5, True, 2, 5),
        (5, 5, True, 1, 5),
        (3, 5, True, 1, 5),  # num_images // num_filter floors to 0, clamped to 1
        (0, 5, True, 1, 5),
        (100, 10, True, 10, 10),
        (10, 5, False, 10, 1),  # num_filter ignored when filtering is disabled
    ],
)
async def test_default_trigger_info_with_process_plugin(
    num_images, num_filter, enable_filter, expected_collections, expected_exposures
):
    async with init_devices(mock=True):
        driver = adcore.ADBaseIO("PREFIX:")
        process_plugin = adcore.NDProcessIO("PREFIX:PROC:")
    set_mock_value(driver.num_images, num_images)
    set_mock_value(process_plugin.num_filter, num_filter)
    set_mock_value(process_plugin.enable_filter, enable_filter)

    trigger_logic = adsimdetector.SimDetectorTriggerLogic(driver, process_plugin)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.trigger == DetectorTrigger.INTERNAL
    assert trigger_info.collections_per_event == expected_collections
    assert trigger_info.exposures_per_collection == expected_exposures
