import re

import pytest
from bluesky.run_engine import RunEngine
from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    TriggerInfo,
    set_sim_value,
)
from ophyd_async.epics.areadetector.aravis import ADAravisDetector
from ophyd_async.epics.areadetector.controllers.aravis_controller import ADAravisController
from ophyd_async.epics.areadetector.drivers.aravis_driver import ADAravisDriver, ADAravisTriggerSource

@pytest.fixture
async def adaravis_driver(RE: RunEngine) -> ADAravisDriver:
    async with DeviceCollector(sim=True):
        driver = ADAravisDriver("DRV:")

    return driver


@pytest.fixture
async def adaravis_controller(
    RE: RunEngine, adaravis_driver: ADAravisDriver
) -> ADAravisController:
    async with DeviceCollector(sim=True):
        controller = ADAravisController(adaravis_driver, gpio_number=1)

    return controller


@pytest.fixture
async def adaravis(
    RE: RunEngine, static_directory_provider: DirectoryProvider
) -> ADAravisDetector:
    async with DeviceCollector(sim=True):
        adaravis = ADAravisDetector(
            "ADARAVIS:",
            static_directory_provider,
            name="adaravis",
        )

    return adaravis


@pytest.mark.parametrize(
    "model,pixel_format,deadtime",
    [
        ("Manta G-125", "Mono12Packed", 63e-6),
        ("Manta G-125B", "Mono12Packed", 63e-6),
        ("Manta G-125", "Mono8", 63e-6),
        ("Manta G-125B", "Mono8", 63e-6),
        ("Manta G-235", "Mono8", 118e-6),
        ("Manta G-235B", "Mono8", 118e-6),
        ("Manta G-235", "RGB8Packed", 390e-6),
        ("Manta G-235B", "RGB8Packed", 390e-6),
        ("Manta G-609", "", 47e-6),
        ("Manta G-609", "foo", 47e-6),
        ("Manta G-609", None, 47e-6),
    ],
)
async def test_deadtime_read_from_file(
    model: str,
    pixel_format: str,
    deadtime: float,
    adaravis_controller: ADAravisController,
):
    set_sim_value(adaravis_controller._drv.model, model)
    set_sim_value(adaravis_controller._drv.pixel_format, pixel_format)

    # deadtime invariant with exposure time
    await adaravis_controller._fetch_deadtime()
    assert adaravis_controller.get_deadtime(0) == deadtime
    await adaravis_controller._fetch_deadtime()
    assert adaravis_controller.get_deadtime(500) == deadtime


async def test_trigger_source_set_to_gpio_line(adaravis: ADAravisDetector):
    async def trigger_and_complete():
        await adaravis.controller.arm(num=1, trigger=DetectorTrigger.edge_trigger)
        # Prevent timeouts
        set_sim_value(adaravis.controller._drv.acquire, True)

    # Default TriggerSource
    assert (
        await adaravis._controller._drv.trigger_source.get_value()
    ) == ADAravisTriggerSource.freerun
    adaravis.set_external_trigger_gpio(1)
    # TriggerSource not changed by setting gpio
    assert (
        await adaravis._controller._drv.trigger_source.get_value()
    ) == ADAravisTriggerSource.freerun

    await trigger_and_complete()

    # TriggerSource changes
    assert (
        await adaravis._controller._drv.trigger_source.get_value()
    ) == ADAravisTriggerSource.line_1

    adaravis.set_external_trigger_gpio(3)
    # TriggerSource not changed by setting gpio
    await trigger_and_complete()
    assert (
        await adaravis._controller._drv.trigger_source.get_value()
    ) == ADAravisTriggerSource.line_3


def test_gpio_pin_limited(adaravis: ADAravisDetector):
    assert adaravis.get_external_trigger_gpio() == 1
    adaravis.set_external_trigger_gpio(2)
    assert adaravis.get_external_trigger_gpio() == 2
    with pytest.raises(
        ValueError,
        match=re.escape(
            "ADAravisDetector only supports the following GPIO indices: (1, 2, 3, 4) but was asked to use 55"
        ),
    ):
        adaravis.set_external_trigger_gpio(55)  # type: ignore


async def test_hints_from_hdf_writer(adaravis: ADAravisDetector):
    assert adaravis.hints == {"fields": ["adaravis"]}


async def test_unsupported_trigger_excepts(adaravis: ADAravisDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"ADAravisController only supports the following trigger types: .* but",
    ):
        await adaravis.prepare(TriggerInfo(1, DetectorTrigger.variable_gate, 1, 1))
