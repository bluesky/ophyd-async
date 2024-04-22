import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    TriggerInfo,
    set_sim_value,
)
from ophyd_async.epics.areadetector.controllers.pilatus_controller import (
    PilatusController,
)
from ophyd_async.epics.areadetector.drivers.pilatus_driver import (
    PilatusDriver,
    PilatusTriggerMode,
)
from ophyd_async.epics.areadetector.pilatus import PilatusDetector
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF


@pytest.fixture
async def pilatus_driver(RE: RunEngine) -> PilatusDriver:
    async with DeviceCollector(sim=True):
        driver = PilatusDriver("DRV:")

    return driver


@pytest.fixture
async def pilatus_controller(
    RE: RunEngine, pilatus_driver: PilatusDriver
) -> PilatusController:
    async with DeviceCollector(sim=True):
        controller = PilatusController(pilatus_driver)

    return controller


@pytest.fixture
async def hdf(RE: RunEngine) -> NDFileHDF:
    async with DeviceCollector(sim=True):
        hdf = NDFileHDF("HDF:")

    return hdf


@pytest.fixture
async def pilatus(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
    pilatus_driver: PilatusDriver,
    hdf: NDFileHDF,
) -> PilatusDetector:
    async with DeviceCollector(sim=True):
        pilatus = PilatusDetector(
            "pilatus",
            static_directory_provider,
            driver=pilatus_driver,
            hdf=hdf,
        )

    return pilatus


async def test_deadtime_invariant(
    pilatus_controller: PilatusController,
):
    # deadtime invariant with exposure time
    assert pilatus_controller.get_deadtime(0) == 2.28e-3
    assert pilatus_controller.get_deadtime(500) == 2.28e-3


@pytest.mark.parametrize(
    "detector_trigger,expected_trigger_mode",
    [
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
        (DetectorTrigger.internal, PilatusTriggerMode.internal),
    ],
)
async def test_trigger_mode_set(
    pilatus: PilatusDetector,
    detector_trigger: DetectorTrigger,
    expected_trigger_mode: PilatusTriggerMode,
):
    async def trigger_and_complete():
        await pilatus.controller.arm(num=1, trigger=detector_trigger)
        # Prevent timeouts
        set_sim_value(pilatus.controller._drv.acquire, True)

    # Default TriggerMode
    assert (await pilatus.drv.trigger_mode.get_value()) == PilatusTriggerMode.internal

    await trigger_and_complete()

    # TriggerSource changes
    assert (await pilatus.drv.trigger_mode.get_value()) == expected_trigger_mode


async def test_hints_from_hdf_writer(pilatus: PilatusDetector):
    assert pilatus.hints == {"fields": ["pilatus"]}


async def test_unsupported_trigger_excepts(pilatus: PilatusDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"PilatusController only supports the following trigger types: .* but",
    ):
        await pilatus.prepare(TriggerInfo(1, DetectorTrigger.edge_trigger, 1, 1))
