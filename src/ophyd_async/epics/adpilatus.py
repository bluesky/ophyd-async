"""Support for the ADPilatus areaDetector driver.

https://github.com/areaDetector/ADPilatus
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated as A

from ophyd_async.core import (
    DetectorTrigger,
    DetectorTriggerLogic,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
    SupersetEnum,
    TriggerableCommand,
)

from .adcore import (
    ADAcquireLogic,
    ADBaseIO,
    ADWriterFactory,
    AreaDetector,
    NDPluginBaseIO,
    NDProcessIO,
    default_trigger_info_from_detector_settings,
    prepare_exposures,
)
from .core import PvSuffix

__all__ = [
    "PilatusDetector",
    "PilatusDriverIO",
    "PilatusGain",
    "PilatusTriggerLogic",
    "PilatusTriggerMode",
    "PilatusReadoutTime",
]

_MAX_NUM_IMAGE = 999_999


class PilatusTriggerMode(StrictEnum):
    """Trigger modes for ADPilatus detector."""

    INTERNAL = "Internal"
    EXT_ENABLE = "Ext. Enable"
    EXT_TRIGGER = "Ext. Trigger"
    MULT_TRIGGER = "Mult. Trigger"
    ALIGNMENT = "Alignment"


class PilatusGain(SupersetEnum):
    """Shaping time and gain settings for the ADPilatus detector."""

    FAST_LOW = "7-30KeV/Fast/LowG"
    MEDIUM_MEDIUM = "5-18KeV/Med/MedG"
    SLOW_HIGH = "3-6KeV/Slow/HighG"
    SLOW_ULTRAHIGH = "2-5KeV/Slow/UltraG"


class PilatusDriverIO(ADBaseIO):
    """Driver for the Pilatus pixel array detectors."""

    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""
    """See HTML docs at https://areadetector.github.io/areaDetector/ADPilatus/pilatusDoc.html"""
    trigger_mode: A[SignalRW[PilatusTriggerMode], PvSuffix.rbv("TriggerMode")]
    armed: A[SignalR[bool], PvSuffix("Armed")]
    header_string: A[SignalRW[str], PvSuffix("HeaderString")]
    energy: A[SignalRW[float], PvSuffix.rbv("Energy")]
    threshold_energy: A[SignalRW[float], PvSuffix.rbv("ThresholdEnergy")]
    gain_menu: A[SignalRW[PilatusGain], PvSuffix("GainMenu")]
    threshold_auto_apply: A[SignalRW[bool], PvSuffix.rbv("ThresholdAutoApply")]
    threshold_apply: A[TriggerableCommand, PvSuffix("ThresholdApply")]


class PilatusReadoutTime(float, Enum):
    """Pilatus readout time per model in ms."""

    # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
    PILATUS2 = 2.28e-3

    # Cite: https://media.dectris.com/user-manual-pilatus3-2020.pdf
    PILATUS3 = 0.95e-3


@dataclass
class PilatusTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADPilatus detectors."""

    driver: PilatusDriverIO
    readout_time: PilatusReadoutTime
    process_plugin: NDProcessIO | None = None
    edge_trigger_mode: PilatusTriggerMode = field(
        default=PilatusTriggerMode.EXT_TRIGGER, kw_only=True
    )

    def __post_init__(self):
        """Validate `edge_trigger_mode` is a trigger-capable mode."""
        if self.edge_trigger_mode not in (
            PilatusTriggerMode.EXT_TRIGGER,
            PilatusTriggerMode.MULT_TRIGGER,
        ):
            raise ValueError(
                "edge_trigger_mode must be PilatusTriggerMode.EXT_TRIGGER or "
                "PilatusTriggerMode.MULT_TRIGGER"
            )

    def get_deadtime(self, config_values: SignalDict) -> float:
        return self.readout_time

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.trigger_mode.set(PilatusTriggerMode.INTERNAL)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime, deadtime)

    async def prepare_edge(self, num: int, livetime: float):
        await self.driver.trigger_mode.set(self.edge_trigger_mode)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE, livetime)

    async def prepare_level(self, num: int):
        await self.driver.trigger_mode.set(PilatusTriggerMode.EXT_ENABLE)
        await prepare_exposures(self.driver, num or _MAX_NUM_IMAGE)

    async def default_trigger_info(self):
        trigger_mode = await self.driver.trigger_mode.get_value()
        det_trigger = DetectorTrigger.INTERNAL
        if trigger_mode == PilatusTriggerMode.EXT_TRIGGER:
            det_trigger = DetectorTrigger.EXTERNAL_EDGE
        elif trigger_mode == PilatusTriggerMode.EXT_ENABLE:
            det_trigger = DetectorTrigger.EXTERNAL_LEVEL

        return await default_trigger_info_from_detector_settings(
            self.driver.num_images, self.process_plugin, detector_trigger=det_trigger
        )


class PilatusDetector(AreaDetector[PilatusDriverIO]):
    """Create an ADPilatus AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param writer_factories: Factories for file writer plugins and their data logics
    :param readout_time: Readout time for the specific Pilatus model
    :param edge_trigger_mode: Trigger mode the driver is set to for external
        edge-triggered acquisitions. Defaults to `PilatusTriggerMode.EXT_TRIGGER`
        (one trigger starts a burst of `num` images); set to
        `PilatusTriggerMode.MULT_TRIGGER` for one image per trigger pulse.
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
        readout_time: PilatusReadoutTime = PilatusReadoutTime.PILATUS3,
        edge_trigger_mode: PilatusTriggerMode = PilatusTriggerMode.EXT_TRIGGER,
        driver_suffix="cam1:",
        proc_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = PilatusDriverIO(prefix + driver_suffix)
        proc_plugin = NDProcessIO(prefix + proc_suffix) if proc_suffix else None
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADAcquireLogic(driver, driver_armed_signal=driver.armed),
            trigger_logic=PilatusTriggerLogic(
                driver, readout_time, proc_plugin, edge_trigger_mode=edge_trigger_mode
            ),
            plugins=(plugins or {}) | ({"proc": proc_plugin} if proc_plugin else {}),
            config_sigs=config_sigs,
            name=name,
        )
