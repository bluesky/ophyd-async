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
from .adgenicam import get_camera_deadtime
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

    def __init__(self, driver: AravisDriverIO, override_deadtime: float | None = None):
        self.driver = driver
        self.override_deadtime = override_deadtime

    def config_sigs(self) -> set[SignalR]:
        return {self.driver.model}

    def get_deadtime(self, config_values: SignalDict) -> float:
        return get_camera_deadtime(
            model=config_values[self.driver.model],
            override_deadtime=self.override_deadtime,
        )

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(OnOff.OFF)
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        # Trigger on the rising edge of Line1
        # trigger mode must be set first and on its own!
        # https://github.com/AravisProject/aravis/issues/1045
        await self.driver.trigger_mode.set(OnOff.ON)
        await self.driver.trigger_source.set(AravisTriggerSource.LINE1)
        await prepare_exposures(self.driver, num, livetime)


class AravisDetector(AreaDetector[AravisDriverIO]):
    """Create an ADAravis AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param override_deadtime:
        If provided, this value is used for deadtime instead of looking up
        based on camera model.
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
        override_deadtime: float | None = None,
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = AravisDriverIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADArmLogic(driver),
            trigger_logic=AravisTriggerLogic(driver, override_deadtime),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
