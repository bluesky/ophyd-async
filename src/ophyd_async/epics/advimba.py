"""Support for the ADVimba areaDetector driver.

https://github.com/areaDetector/ADVimba.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTriggerLogic,
    OnOff,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
)
from ophyd_async.epics.core import PvSuffix

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

__all__ = [
    "VimbaDetector",
    "VimbaDriverIO",
    "VimbaTriggerLogic",
    "VimbaConvertFormat",
    "VimbaTriggerSource",
    "VimbaOverlap",
    "VimbaExposeOutMode",
]


class VimbaConvertFormat(StrictEnum):
    """Convert pixel format for the Vimba detector."""

    NONE = "None"
    MONO8 = "Mono8"
    MONO16 = "Mono16"
    RGB8 = "RGB8"
    RGB16 = "RGB16"


class VimbaTriggerSource(StrictEnum):
    """Mode for the source of triggers on the Vimba."""

    FREERUN = "Freerun"
    LINE1 = "Line1"
    LINE2 = "Line2"
    FIXED_RATE = "FixedRate"
    SOFTWARE = "Software"
    ACTION0 = "Action0"
    ACTION1 = "Action1"


class VimbaOverlap(StrictEnum):
    """Overlap modes for the Vimba detector."""

    OFF = OnOff.OFF.value
    PREV_FRAME = "PreviousFrame"


class VimbaExposeOutMode(StrictEnum):
    """Exposure control modes for Vimba detectors."""

    TIMED = "Timed"  # Use ExposureTime PV
    TRIGGER_WIDTH = "TriggerWidth"  # Expose for length of high signal


class VimbaDriverIO(ADBaseIO):
    """Mirrors the interface provided by ADVimba/db/vimba.template."""

    convert_pixel_format: A[
        SignalRW[VimbaConvertFormat], PvSuffix.rbv("ConvertPixelFormat")
    ]
    trigger_source: A[SignalRW[VimbaTriggerSource], PvSuffix.rbv("TriggerSource")]
    trigger_mode: A[SignalRW[OnOff], PvSuffix.rbv("TriggerMode")]
    trigger_overlap: A[SignalRW[VimbaOverlap], PvSuffix.rbv("TriggerOverlap")]
    exposure_mode: A[SignalRW[VimbaExposeOutMode], PvSuffix.rbv("ExposureMode")]


@dataclass
class VimbaTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADVimba detectors."""

    driver: VimbaDriverIO
    override_deadtime: float | None = None

    def config_sigs(self) -> set[SignalR]:
        return {self.driver.model}

    def get_deadtime(self, config_values: SignalDict) -> float:
        return get_camera_deadtime(
            model=config_values[self.driver.model],
            override_deadtime=self.override_deadtime,
        )

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await asyncio.gather(
            self.driver.trigger_mode.set(OnOff.OFF),
            self.driver.exposure_mode.set(VimbaExposeOutMode.TIMED),
            self.driver.trigger_source.set(VimbaTriggerSource.FREERUN),
        )
        await prepare_exposures(self.driver, num, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await asyncio.gather(
            self.driver.trigger_mode.set(OnOff.ON),
            self.driver.exposure_mode.set(VimbaExposeOutMode.TIMED),
            self.driver.trigger_source.set(VimbaTriggerSource.LINE1),
        )
        await prepare_exposures(self.driver, num, livetime)

    async def prepare_level(self, num: int):
        await asyncio.gather(
            self.driver.trigger_mode.set(OnOff.ON),
            self.driver.exposure_mode.set(VimbaExposeOutMode.TRIGGER_WIDTH),
            self.driver.trigger_source.set(VimbaTriggerSource.LINE1),
        )
        await prepare_exposures(self.driver, num)

    async def default_trigger_info(self):
        return await trigger_info_from_num_images(self.driver)


class VimbaDetector(AreaDetector[VimbaDriverIO]):
    """Create an ADVimba AreaDetector instance.

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
        driver = VimbaDriverIO(prefix + driver_suffix)
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver),
            trigger_logic=VimbaTriggerLogic(driver, override_deadtime),
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
