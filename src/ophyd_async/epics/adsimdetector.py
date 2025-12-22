"""Support for the SimDetector areaDetector driver.

https://github.com/areaDetector/ADSimDetector.
"""

from collections.abc import Sequence

from ophyd_async.core import (
    DetectorTriggerLogic,
    PathProvider,
    SignalR,
)
from ophyd_async.epics.adcore import (
    ADArmLogic,
    ADBaseIO,
    ADWriterType,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
)


class SimDetectorTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADSimDetector."""

    def __init__(self, driver: ADBaseIO):
        self.driver = driver

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await prepare_exposures(self.driver, num, livetime, deadtime)


def sim_detector(
    prefix: str,
    path_provider: PathProvider,
    driver_suffix="cam1:",
    writer_type: ADWriterType = ADWriterType.HDF,
    writer_suffix: str | None = None,
    plugins: dict[str, NDPluginBaseIO] | None = None,
    config_sigs: Sequence[SignalR] = (),
    name: str = "",
) -> AreaDetector:
    """Create an ADSimDetector AreaDetector instance.

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
    driver = ADBaseIO(prefix + driver_suffix)
    return writer_type.make_detector(
        prefix=prefix,
        path_provider=path_provider,
        writer_suffix=writer_suffix,
        driver=driver,
        trigger_logic=SimDetectorTriggerLogic(driver),
        arm_logic=ADArmLogic(driver),
        plugins=plugins,
        config_sigs=config_sigs,
        name=name,
    )
