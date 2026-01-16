"""Support for the ADAndor areaDetector driver.

https://github.com/areaDetector/ADAndor.
"""

from collections.abc import Sequence
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTriggerLogic,
    PathProvider,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
)
from ophyd_async.epics.adcore import (
    ADArmLogic,
    ADBaseIO,
    ADWriterType,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
)
from ophyd_async.epics.core import PvSuffix

_MIN_DEAD_TIME = 0.1
_MAX_NUM_IMAGE = 999_999


class Andor2TriggerMode(StrictEnum):
    """Trigger modes for ADAndor detector."""

    INTERNAL = "Internal"
    EXT_TRIGGER = "External"
    EXT_START = "External Start"
    EXT_EXPOSURE = "External Exposure"
    EXT_FVP = "External FVP"
    SOFTWARE = "Software"


class Andor2DriverIO(ADBaseIO):
    """Driver for andor model:DU897_BV as deployed on p99.

    This mirrors the interface provided by AdAndor/db/andor.template.
    https://areadetector.github.io/areaDetector/ADAndor/andorDoc.html
    """

    trigger_mode: A[SignalRW[Andor2TriggerMode], PvSuffix.rbv("TriggerMode")]
    andor_accumulate_period: A[SignalR[float], PvSuffix("AndorAccumulatePeriod_RBV")]


# The deadtime of an Andor2 controller varies depending on the exact model of camera.
# Ideally we would maximize performance by dynamically retrieving the deadtime at
# runtime. See https://github.com/bluesky/ophyd-async/issues/308
class Andor2TriggerLogic(DetectorTriggerLogic):
    """DetectorCobntroller for Andor2DriverIO."""

    def __init__(self, driver: Andor2DriverIO):
        self.driver = driver

    def get_deadtime(self, config_values: SignalDict) -> float:
        return _MIN_DEAD_TIME

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(Andor2TriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await self.driver.trigger_mode.set(Andor2TriggerMode.EXT_TRIGGER)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime)


class AndorDetector(AreaDetector[Andor2DriverIO]):
    """Create an ADAndor AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param writer_type: Type of file writer (HDF or TIFF)
    :param writer_suffix: Suffix for the writer PV
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider | None = None,
        driver_suffix="cam1:",
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = Andor2DriverIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADArmLogic(driver),
            trigger_logic=Andor2TriggerLogic(driver),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
