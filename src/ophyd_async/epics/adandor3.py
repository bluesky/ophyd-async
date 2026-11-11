"""Support for the ADAndor areaDetector driver.

https://github.com/areaDetector/ADAndor3.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTriggerLogic,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
)
from ophyd_async.epics.adcore import (
    ADAcquireLogic,
    ADBaseIO,
    ADWriterFactory,
    AreaDetector,
    NDPluginBaseIO,
    NDProcessIO,
    prepare_filter,
    trigger_info_from_driver,
)
from ophyd_async.epics.core import PvSuffix

__all__ = [
    "Andor3Detector",
    "Andor3DriverIO",
    "Andor3TriggerLogic",
    "Andor3TriggerMode",
]

_MIN_DEAD_TIME = 0.1
_MAX_NUM_IMAGE = 999_999


class Andor3TriggerMode(StrictEnum):
    """Trigger modes for ADAndor detector."""

    INTERNAL = "Internal"
    EXT_TRIGGER = "External"
    EXT_START = "External Start"
    EXT_EXPOSURE = "External Exposure"
    EXT_FVP = "External FVP"
    SOFTWARE = "Software"


class Andor3ImageMode(SubsetEnum):
    """Image modes for the ADAndor3 detector."""

    FIXED = "Fixed"
    CONTINUOUS = "Continuous"


class Andor3DriverIO(ADBaseIO):
    """Driver for andor marana as deployed on i08-1.

    This mirrors the interface provided by AdAndor3/db/andor3.template.
    https://areadetector.github.io/areaDetector/ADAndor3/ADAndorDoc.html
    """

    trigger_mode: A[SignalRW[Andor3TriggerMode], PvSuffix.rbv("TriggerMode")]
    readout_time: A[SignalR[float], PvSuffix("ReadoutTime")]
    image_mode: A[SignalRW[Andor3ImageMode], PvSuffix.rbv("ImageMode")]


async def prepare_exposures(
    driver: Andor3DriverIO,
    num: int,
    livetime: float = 0.0,
    deadtime: float = 0.0,
) -> None:
    """Prepare the driver for a given num exposures with specified livetime, deadtime.

    :param driver: The ADBaseIO driver instance
    :param num: Number of exposures to prepare
    :param livetime: Exposure time for each image (default: 0.0)
    :param deadtime: Deadtime between exposures (default: 0.0)
    """
    image_mode = Andor3ImageMode.CONTINUOUS if num == 0 else Andor3ImageMode.FIXED
    coros = [
        driver.image_mode.set(image_mode),
        driver.num_images.set(num),
    ]
    if livetime:
        coros.append(driver.acquire_time.set(livetime))
        if deadtime:
            coros.append(driver.acquire_period.set(livetime + deadtime))
    await asyncio.gather(*coros)


@dataclass
class Andor3TriggerLogic(DetectorTriggerLogic):
    """Trigger logic for Andor3DriverIO."""

    driver: Andor3DriverIO
    process_plugin: NDProcessIO | None

    def get_deadtime(self, config_values: SignalDict) -> float:
        return _MIN_DEAD_TIME

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(Andor3TriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await self.driver.trigger_mode.set(Andor3TriggerMode.EXT_TRIGGER)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime)

    async def prepare_exposures_per_collection(self, exposures_per_collection: int):
        await prepare_filter(self.process_plugin, exposures_per_collection)

    async def default_trigger_info(self):
        return await trigger_info_from_driver(
            self.driver.num_images, self.process_plugin
        )


class Andor3Detector(AreaDetector[Andor3DriverIO]):
    """Create an ADAndor AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param writer_factories: Factories for file writer plugins and their data logics
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param proc_suffix: If provided, an NDProcessIO plugin is created at this suffix
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        *writer_factories: ADWriterFactory,
        driver_suffix="cam1:",
        proc_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = Andor3DriverIO(prefix + driver_suffix)
        proc_plugin = NDProcessIO(prefix + proc_suffix) if proc_suffix else None
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver),
            trigger_logic=Andor3TriggerLogic(driver, proc_plugin),
            plugins=(plugins or {}) | ({"proc": proc_plugin} if proc_plugin else {}),
            config_sigs=config_sigs,
            name=name,
        )
