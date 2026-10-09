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

# id, driver_class, trigger_logic_class, extra_args, mode_settings, expected_trigger
_TRIGGER_MODE_CASES = [
    pytest.param(
        adcore.ADBaseIO,
        adsimdetector.SimDetectorTriggerLogic,
        (),
        {},
        DetectorTrigger.INTERNAL,
        id="sim-internal",
    ),
    pytest.param(
        adandor.Andor2DriverIO,
        adandor.Andor2TriggerLogic,
        (),
        {"trigger_mode": adandor.Andor2TriggerMode.INTERNAL},
        DetectorTrigger.INTERNAL,
        id="andor2-internal",
    ),
    pytest.param(
        adandor.Andor2DriverIO,
        adandor.Andor2TriggerLogic,
        (),
        {"trigger_mode": adandor.Andor2TriggerMode.EXT_TRIGGER},
        DetectorTrigger.EXTERNAL_EDGE,
        id="andor2-edge",
    ),
    pytest.param(
        adaravis.AravisDriverIO,
        adaravis.AravisTriggerLogic,
        (),
        {"trigger_mode": OnOff.OFF},
        DetectorTrigger.INTERNAL,
        id="aravis-internal",
    ),
    pytest.param(
        adaravis.AravisDriverIO,
        adaravis.AravisTriggerLogic,
        (),
        {"trigger_mode": OnOff.ON},
        DetectorTrigger.EXTERNAL_EDGE,
        id="aravis-edge",
    ),
    pytest.param(
        adkinetix.KinetixDriverIO,
        adkinetix.KinetixTriggerLogic,
        (),
        {"trigger_mode": adkinetix.KinetixTriggerMode.INTERNAL},
        DetectorTrigger.INTERNAL,
        id="kinetix-internal",
    ),
    pytest.param(
        adkinetix.KinetixDriverIO,
        adkinetix.KinetixTriggerLogic,
        (),
        {"trigger_mode": adkinetix.KinetixTriggerMode.EDGE},
        DetectorTrigger.EXTERNAL_EDGE,
        id="kinetix-edge",
    ),
    pytest.param(
        adkinetix.KinetixDriverIO,
        adkinetix.KinetixTriggerLogic,
        (),
        {"trigger_mode": adkinetix.KinetixTriggerMode.GATE},
        DetectorTrigger.EXTERNAL_LEVEL,
        id="kinetix-level",
    ),
    pytest.param(
        admerlin.MerlinDriverIO,
        admerlin.MerlinTriggerLogic,
        (),
        {"trigger_mode": admerlin.MerlinTriggerMode.INTERNAL},
        DetectorTrigger.INTERNAL,
        id="merlin-internal",
    ),
    pytest.param(
        admerlin.MerlinDriverIO,
        admerlin.MerlinTriggerLogic,
        (),
        {"trigger_mode": admerlin.MerlinTriggerMode.TRIGGER_START_RISING},
        DetectorTrigger.EXTERNAL_EDGE,
        id="merlin-edge",
    ),
    pytest.param(
        adpilatus.PilatusDriverIO,
        adpilatus.PilatusTriggerLogic,
        (adpilatus.PilatusReadoutTime.PILATUS3,),
        {"trigger_mode": adpilatus.PilatusTriggerMode.INTERNAL},
        DetectorTrigger.INTERNAL,
        id="pilatus-internal",
    ),
    pytest.param(
        adpilatus.PilatusDriverIO,
        adpilatus.PilatusTriggerLogic,
        (adpilatus.PilatusReadoutTime.PILATUS3,),
        {"trigger_mode": adpilatus.PilatusTriggerMode.EXT_TRIGGER},
        DetectorTrigger.EXTERNAL_EDGE,
        id="pilatus-edge",
    ),
    pytest.param(
        adpilatus.PilatusDriverIO,
        adpilatus.PilatusTriggerLogic,
        (adpilatus.PilatusReadoutTime.PILATUS3,),
        {"trigger_mode": adpilatus.PilatusTriggerMode.EXT_ENABLE},
        DetectorTrigger.EXTERNAL_LEVEL,
        id="pilatus-level",
    ),
    pytest.param(
        advimba.VimbaDriverIO,
        advimba.VimbaTriggerLogic,
        (),
        {
            "trigger_mode": OnOff.OFF,
            "exposure_mode": advimba.VimbaExposeOutMode.TIMED,
        },
        DetectorTrigger.INTERNAL,
        id="vimba-internal",
    ),
    pytest.param(
        advimba.VimbaDriverIO,
        advimba.VimbaTriggerLogic,
        (),
        {
            "trigger_mode": OnOff.ON,
            "exposure_mode": advimba.VimbaExposeOutMode.TIMED,
        },
        DetectorTrigger.EXTERNAL_EDGE,
        id="vimba-edge",
    ),
    pytest.param(
        advimba.VimbaDriverIO,
        advimba.VimbaTriggerLogic,
        (),
        {
            "trigger_mode": OnOff.ON,
            "exposure_mode": advimba.VimbaExposeOutMode.TRIGGER_WIDTH,
        },
        DetectorTrigger.EXTERNAL_LEVEL,
        id="vimba-level",
    ),
]


@pytest.mark.parametrize(
    "driver_class, trigger_logic_class, extra_args, mode_settings, expected_trigger",
    _TRIGGER_MODE_CASES,
)
async def test_default_trigger_info_maps_trigger_mode(
    driver_class, trigger_logic_class, extra_args, mode_settings, expected_trigger
):
    async with init_devices(mock=True):
        driver = driver_class("PREFIX:")
    for name, value in mode_settings.items():
        set_mock_value(getattr(driver, name), value)
    set_mock_value(driver.num_images, 5)

    trigger_logic = trigger_logic_class(driver, *extra_args)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.trigger == expected_trigger
    assert trigger_info.collections_per_event == 5
    assert trigger_info.exposures_per_collection == 1


# id, driver_class, trigger_logic_class, extra_args, mode_settings
_INVALID_TRIGGER_MODE_CASES = [
    pytest.param(
        adandor.Andor2DriverIO,
        adandor.Andor2TriggerLogic,
        (),
        {"trigger_mode": adandor.Andor2TriggerMode.SOFTWARE},
        id="andor2-software",
    ),
    pytest.param(
        adandor.Andor2DriverIO,
        adandor.Andor2TriggerLogic,
        (),
        {"trigger_mode": adandor.Andor2TriggerMode.EXT_EXPOSURE},
        id="andor2-ext-exposure",
    ),
    pytest.param(
        admerlin.MerlinDriverIO,
        admerlin.MerlinTriggerLogic,
        (),
        {"trigger_mode": admerlin.MerlinTriggerMode.SOFTWARE},
        id="merlin-software",
    ),
    pytest.param(
        admerlin.MerlinDriverIO,
        admerlin.MerlinTriggerLogic,
        (),
        {"trigger_mode": admerlin.MerlinTriggerMode.TRIGGER_ENABLE},
        id="merlin-trigger-enable",
    ),
]


@pytest.mark.parametrize(
    "driver_class, trigger_logic_class, extra_args, mode_settings",
    _INVALID_TRIGGER_MODE_CASES,
)
async def test_default_trigger_info_rejects_unsupported_trigger_mode(
    driver_class, trigger_logic_class, extra_args, mode_settings
):
    async with init_devices(mock=True):
        driver = driver_class("PREFIX:")
    for name, value in mode_settings.items():
        set_mock_value(getattr(driver, name), value)

    trigger_logic = trigger_logic_class(driver, *extra_args)
    with pytest.raises(ValueError, match="trigger type"):
        await trigger_logic.default_trigger_info()


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

    trigger_logic = adsimdetector.SimDetectorTriggerLogic(driver)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.collections_per_event == expected_collections_per_event
    assert trigger_info.exposures_per_collection == 1


@pytest.mark.parametrize(
    "num_images, num_filter, expected_collections, expected_exposures",
    [
        (10, 5, 2, 5),
        (5, 5, 1, 5),
        (3, 5, 1, 5),  # num_images // num_filter floors to 0, clamped to 1
        (0, 5, 1, 5),
        (100, 10, 10, 10),
    ],
)
async def test_default_trigger_info_with_process_plugin(
    num_images, num_filter, expected_collections, expected_exposures
):
    async with init_devices(mock=True):
        driver = adcore.ADBaseIO("PREFIX:")
        process_plugin = adcore.NDProcessIO("PREFIX:PROC:")
    set_mock_value(driver.num_images, num_images)
    set_mock_value(process_plugin.num_filter, num_filter)

    trigger_logic = adsimdetector.SimDetectorTriggerLogic(driver, process_plugin)
    trigger_info = await trigger_logic.default_trigger_info()

    assert trigger_info.trigger == DetectorTrigger.INTERNAL
    assert trigger_info.collections_per_event == expected_collections
    assert trigger_info.exposures_per_collection == expected_exposures
