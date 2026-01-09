"""areaDetector support for Aravis GigE and USB3 vision cameras.

https://github.com/areaDetector/ADAravis
"""

from collections.abc import Sequence
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTriggerLogic,
    OnOff,
    PathProvider,
    SignalDict,
    SignalR,
    SignalRW,
    SubsetEnum,
)

from .adcore import (
    ADArmLogic,
    ADBaseIO,
    ADWriterType,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
)
from .adgenicam import camera_deadtimes
from .core import PvSuffix


class AravisTriggerSource(SubsetEnum):
    """Which trigger source to use when TriggerMode=On."""

    LINE1 = "Line1"


class AravisDriverIO(ADBaseIO):
    """Generic Driver supporting all GiGE cameras.

    This mirrors the interface provided by ADAravis/db/aravisCamera.template.
    """

    trigger_mode: A[SignalRW[OnOff], PvSuffix.rbv("TriggerMode")]
    trigger_source: A[SignalRW[AravisTriggerSource], PvSuffix.rbv("TriggerSource")]


class AravisTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for Aravis GigE and USB3 cameras."""

    def __init__(self, driver: AravisDriverIO):
        self.driver = driver

    def config_sigs(self) -> set[SignalR]:
        return {self.driver.model}

    def get_deadtime(self, config_values: SignalDict) -> float:
        return camera_deadtimes[config_values[self.driver.model]]

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(OnOff.OFF)
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        # Trigger on the rising edge of Line1
        # trigger mode must be set first and on it's own!
        await self.driver.trigger_mode.set(OnOff.ON)
        await self.driver.trigger_source.set(AravisTriggerSource.LINE1)
        await prepare_exposures(self.driver, num, livetime)


def aravis_detector(
    prefix: str,
    path_provider: PathProvider,
    driver_suffix="cam1:",
    writer_type: ADWriterType = ADWriterType.HDF,
    writer_suffix: str | None = None,
    plugins: dict[str, NDPluginBaseIO] | None = None,
    config_sigs: Sequence[SignalR] = (),
    name: str = "",
) -> AreaDetector[AravisDriverIO]:
    """Create an ADAravis AreaDetector instance.

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
    driver = AravisDriverIO(prefix + driver_suffix)
    return writer_type.make_detector(
        prefix=prefix,
        path_provider=path_provider,
        writer_suffix=writer_suffix,
        driver=driver,
        trigger_logic=AravisTriggerLogic(driver),
        arm_logic=ADArmLogic(driver),
        plugins=plugins,
        config_sigs=config_sigs,
        name=name,
    )
