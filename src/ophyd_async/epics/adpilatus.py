"""Support for the ADPilatus areaDetector driver.

https://github.com/areaDetector/ADPilatus
"""

from collections.abc import Sequence
from enum import Enum
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

_MAX_NUM_IMAGE = 999_999


class PilatusTriggerMode(StrictEnum):
    """Trigger modes for ADPilatus detector."""

    INTERNAL = "Internal"
    EXT_ENABLE = "Ext. Enable"
    EXT_TRIGGER = "Ext. Trigger"
    MULT_TRIGGER = "Mult. Trigger"
    ALIGNMENT = "Alignment"


class PilatusDriverIO(ADBaseIO):
    """Driver for the Pilatus pixel array detectors."""

    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""
    """See HTML docs at https://areadetector.github.io/areaDetector/ADPilatus/pilatusDoc.html"""
    trigger_mode: A[SignalRW[PilatusTriggerMode], PvSuffix.rbv("TriggerMode")]
    armed: A[SignalR[bool], PvSuffix("Armed")]


class PilatusReadoutTime(float, Enum):
    """Pilatus readout time per model in ms."""

    # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
    PILATUS2 = 2.28e-3

    # Cite: https://media.dectris.com/user-manual-pilatus3-2020.pdf
    PILATUS3 = 0.95e-3


class PilatusTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADPilatus detectors."""

    def __init__(
        self,
        driver: PilatusDriverIO,
        readout_time: PilatusReadoutTime,
    ):
        self.driver = driver
        self.readout_time = readout_time

    def get_deadtime(self, config_values: SignalDict) -> float:
        return self.readout_time

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(PilatusTriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await self.driver.trigger_mode.set(PilatusTriggerMode.EXT_TRIGGER)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime)

    async def prepare_level(self, num: int):
        await self.driver.trigger_mode.set(PilatusTriggerMode.EXT_ENABLE)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE)


class PilatusDetector(AreaDetector[PilatusDriverIO]):
    """Create an ADPilatus AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
    :param readout_time: Readout time for the specific Pilatus model
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
        readout_time: PilatusReadoutTime = PilatusReadoutTime.PILATUS3,
        driver_suffix="cam1:",
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = PilatusDriverIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADArmLogic(driver, driver_armed_signal=driver.armed),
            trigger_logic=PilatusTriggerLogic(driver, readout_time),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
