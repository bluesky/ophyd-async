"""Support for the SimDetector areaDetector driver.

https://github.com/areaDetector/ADSimDetector.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ophyd_async.core import (
    DetectorTriggerLogic,
    SignalR,
)

from .adcore import (
    ADAcquireLogic,
    ADBaseIO,
    ADWriterFactory,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
    trigger_info_from_num_images,
)

__all__ = [
    "SimDetector",
    "SimDetectorTriggerLogic",
]


@dataclass
class SimDetectorTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADSimDetector."""

    driver: ADBaseIO

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def default_trigger_info(self):
        return await trigger_info_from_num_images(self.driver)


class SimDetector(AreaDetector[ADBaseIO]):
    """Create an ADSimDetector AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param writer_factories: Factories for file writer plugins and their data logics
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        *writer_factories: ADWriterFactory,
        driver_suffix="cam1:",
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = ADBaseIO(prefix + driver_suffix)
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver),
            trigger_logic=SimDetectorTriggerLogic(driver),
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
