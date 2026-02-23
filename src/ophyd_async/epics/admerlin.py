"""Support for the ADMerlin areaDetector driver.

https://github.com/areaDetector/ADMerlin.
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

__all__ = [
    "MerlinDetector",
    "MerlinDriverIO",
    "MerlinTriggerLogic",
    "MerlinTriggerMode",
]

_MIN_DEAD_TIME = 0.002


class MerlinTriggerMode(StrictEnum):
    """Trigger modes for ADMerlin detector."""

    INTERNAL = "Internal"
    TRIGGER_ENABLE = "Trigger Enable"
    TRIGGER_START_RISING = "Trigger start rising"
    TRIGGER_START_FALLING = "Trigger start falling"
    TRIGGER_BOTH_RISING = "Trigger both rising"
    LVDS_TRIG_ENABLE = "LVDS Trig Enable"
    LVDS_TRIG_START_RISING = "LVDS Trig start rising"
    LVDS_TRIG_START_FALLING = "LVDS Trig start falling"
    LVDS_TRIG_BOTH_RISING = "LVDS Trig both rising"
    SOFTWARE = "Software"


class MerlinDriverIO(ADBaseIO):
    """Driver for merlin model:DU897_BV as deployed on p99.

    This mirrors the interface provided by ADMerlin/db/merlin.template.
    https://github.com/areaDetector/ADMerlin/blob/master/merlinApp/Db/merlin.template
    """

    trigger_mode: A[SignalRW[MerlinTriggerMode], PvSuffix.rbv("TriggerMode")]


# The deadtime of an Merlin controller varies depending on the exact model of camera.
# Ideally we would maximize performance by dynamically retrieving the deadtime at
# runtime. See https://github.com/bluesky/ophyd-async/issues/308
class MerlinTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for MerlinDriverIO."""

    def __init__(self, driver: MerlinDriverIO):
        self.driver = driver

    def get_deadtime(self, config_values: SignalDict) -> float:
        return _MIN_DEAD_TIME

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(MerlinTriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        # Is this the right trigger mode?
        await self.driver.trigger_mode.set(MerlinTriggerMode.TRIGGER_START_RISING)
        await prepare_exposures(self.driver, num, livetime)


class MerlinDetector(AreaDetector[MerlinDriverIO]):
    """Create an ADMerlin AreaDetector instance.

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
        driver = MerlinDriverIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADArmLogic(driver),
            trigger_logic=MerlinTriggerLogic(driver),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
