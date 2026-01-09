"""Ophyd-async implementation of an ADKinetix Detector.

https://github.com/NSLS-II/ADKinetix.
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

from .adcore import (
    ADArmLogic,
    ADBaseIO,
    ADWriterType,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
)
from .core import PvSuffix


class KinetixTriggerMode(StrictEnum):
    """Trigger mode for ADKinetix detector."""

    INTERNAL = "Internal"
    EDGE = "Rising Edge"
    GATE = "Exp. Gate"


class KinetixReadoutMode(StrictEnum):
    """Readout mode for ADKinetix detector."""

    SENSITIVITY = "1"
    SPEED = "2"
    DYNAMIC_RANGE = "3"
    SUB_ELECTRON = "4"


class KinetixDriverIO(ADBaseIO):
    """Mirrors the interface provided by ADKinetix/db/ADKinetix.template."""

    trigger_mode: A[SignalRW[KinetixTriggerMode], PvSuffix("TriggerMode")]
    readout_port_idx: A[SignalRW[KinetixReadoutMode], PvSuffix("ReadoutPortIdx")]


class KinetixTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADKinetix detectors."""

    def __init__(self, driver: KinetixDriverIO):
        self.driver = driver

    def get_deadtime(self, config_values: SignalDict) -> float:
        return 0.001

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(KinetixTriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await self.driver.trigger_mode.set(KinetixTriggerMode.EDGE)
        await prepare_exposures(self.driver, num, livetime)

    async def prepare_level(self, num: int):
        await self.driver.trigger_mode.set(KinetixTriggerMode.GATE)
        await prepare_exposures(self.driver, num)


def kinetix_detector(
    prefix: str,
    path_provider: PathProvider,
    driver_suffix="cam1:",
    writer_type: ADWriterType = ADWriterType.HDF,
    writer_suffix: str | None = None,
    plugins: dict[str, NDPluginBaseIO] | None = None,
    config_sigs: Sequence[SignalR] = (),
    name: str = "",
) -> AreaDetector[KinetixDriverIO]:
    """Create an ADKinetix AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param writer_type: Type of file writer (HDF or TIFF)
    :param writer_suffix: Suffix for the writer PV
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    :return: Configured AreaDetector instance
    """
    driver = KinetixDriverIO(prefix + driver_suffix)
    return writer_type.make_detector(
        prefix=prefix,
        path_provider=path_provider,
        writer_suffix=writer_suffix,
        driver=driver,
        trigger_logic=KinetixTriggerLogic(driver),
        arm_logic=ADArmLogic(driver),
        plugins=plugins,
        config_sigs=config_sigs,
        name=name,
    )
