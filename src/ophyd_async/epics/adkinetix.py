"""Ophyd-async implementation of an ADKinetix Detector.

https://github.com/NSLS-II/ADKinetix.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTrigger,
    DetectorTriggerLogic,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
)
from ophyd_async.epics.adcore._io import NDProcessIO

from .adcore import (
    ADAcquireLogic,
    ADBaseIO,
    ADWriterFactory,
    AreaDetector,
    NDPluginBaseIO,
    default_trigger_info_from_detector_settings,
    prepare_exposures,
    prepare_exposures_per_collection,
)
from .core import PvSuffix

__all__ = [
    "KinetixDetector",
    "KinetixDriverIO",
    "KinetixTriggerLogic",
    "KinetixTriggerMode",
    "KinetixReadoutMode",
]


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


@dataclass
class KinetixTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADKinetix detectors."""

    driver: KinetixDriverIO
    process_plugin: NDProcessIO | None = None

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

    async def prepare_exposures_per_collection(self, exposures_per_collection: int):
        if self.process_plugin is not None:
            await prepare_exposures_per_collection(
                self.process_plugin, exposures_per_collection
            )

    async def default_trigger_info(self):
        trigger_mode = await self.driver.trigger_mode.get_value()
        det_trigger = DetectorTrigger.INTERNAL
        if trigger_mode == KinetixTriggerMode.EDGE:
            det_trigger = DetectorTrigger.EXTERNAL_EDGE
        elif trigger_mode == KinetixTriggerMode.GATE:
            det_trigger = DetectorTrigger.EXTERNAL_LEVEL
        return await default_trigger_info_from_detector_settings(
            self.driver.num_images, self.process_plugin, detector_trigger=det_trigger
        )


class KinetixDetector(AreaDetector[KinetixDriverIO]):
    """Create an ADKinetix AreaDetector instance.

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
        driver_suffix: str = "cam1:",
        proc_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = KinetixDriverIO(prefix + driver_suffix)
        proc_plugin = NDProcessIO(prefix + proc_suffix) if proc_suffix else None
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver),
            trigger_logic=KinetixTriggerLogic(driver, proc_plugin),
            plugins=(plugins or {}) | ({"proc": proc_plugin} if proc_plugin else {}),
            config_sigs=config_sigs,
            name=name,
        )
