"""areaDetector support for Aravis GigE and USB3 vision cameras.

https://github.com/areaDetector/ADAravis
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTriggerLogic,
    OnOff,
    SignalDict,
    SignalR,
    SignalRW,
    SubsetEnum,
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
from .adgenicam import get_camera_deadtime
from .core import PvSuffix

__all__ = [
    "AravisDetector",
    "AravisDriverIO",
    "AravisTriggerLogic",
    "AravisTriggerSource",
]


class AravisTriggerSource(SubsetEnum):
    """Which trigger source to use when TriggerMode=On."""

    LINE1 = "Line1"


class AravisDriverIO(ADBaseIO):
    """Generic Driver supporting all GiGE cameras.

    This mirrors the interface provided by ADAravis/db/aravisCamera.template.
    """

    trigger_mode: A[SignalRW[OnOff], PvSuffix.rbv("TriggerMode")]
    trigger_source: A[SignalRW[AravisTriggerSource], PvSuffix.rbv("TriggerSource")]


@dataclass
class AravisTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for Aravis GigE and USB3 cameras."""

    driver: AravisDriverIO
    override_deadtime: float | None = None

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
        # Hardware race condition in Aravis firmware requires setting trigger mode
        # separately before trigger source to avoid undefined behavior.
        # https://github.com/AravisProject/aravis/issues/1045
        await self.driver.trigger_mode.set(OnOff.ON)
        await self.driver.trigger_source.set(AravisTriggerSource.LINE1)
        await prepare_exposures(self.driver, num, livetime)

    async def default_trigger_info(self):
        return await trigger_info_from_num_images(self.driver)


class AravisDetector(AreaDetector[AravisDriverIO]):
    """Create an ADAravis AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param writer_factories: Factories for file writer plugins and their data logics
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param override_deadtime:
        If provided, this value is used for deadtime instead of looking up
        based on camera model.
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        *writer_factories: ADWriterFactory,
        driver_suffix="cam1:",
        override_deadtime: float | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = AravisDriverIO(prefix + driver_suffix)
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver),
            trigger_logic=AravisTriggerLogic(driver, override_deadtime),
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
