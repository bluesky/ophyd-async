"""Ophyd-async implementation of an ADKinetix Detector.

https://github.com/NSLS-II/ADKinetix.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated as A

from bluesky.protocols import Movable

from ophyd_async.core import (
    AsyncStatus,
    DetectorTriggerLogic,
    PathProvider,
    SignalDict,
    SignalR,
    SignalRW,
    StrictEnum,
    SupersetEnum,
)

from .adcore import (
    ADArmLogic,
    ADBaseIO,
    ADWriterType,
    AreaDetector,
    NDPluginBaseIO,
    prepare_exposures,
    trigger_info_from_num_images,
)
from .core import PvSuffix

__all__ = [
    "KinetixDetector",
    "KinetixDriverIO",
    "KinetixTriggerLogic",
    "KinetixTriggerMode",
    "KinetixReadoutMode",
    "KinetixMinExpRes",
    "KinetixSpeedTableIdx",
    "KinetixCommIntf",
    "KinetixFanSpeed",
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


class KinetixMinExpRes(StrictEnum):
    """Minimum exposure time resolution for ADKinetix detector.

    On older firmware versions, only up to 1 ms exposure time resolution
    is supported, while newer versions support up to 1 us.
    """

    SEC = "s"
    MSEC = "ms"
    USEC = "us"


class KinetixSpeedTableIdx(StrictEnum):
    """Speed table index for ADKinetix detector."""

    IDX_0 = "0"
    IDX_1 = "1"
    IDX_2 = "2"
    IDX_3 = "3"


class KinetixCommIntf(StrictEnum):
    """Communication interface for ADKinetix detector."""

    UNKNOWN = "Unknown"
    USB = "USB"
    USB_1_1 = "USB 1.1"
    USB_2_0 = "USB 2.0"
    USB_3_0 = "USB 3.0"
    USB_3_1 = "USB 3.1"
    PCIE = "PCIE"
    PCIE_X1 = "PCIE x1"
    PCIE_X4 = "PCIE x4"
    PCIE_X8 = "PCIE x8"
    VIRTUAL = "Virtual"
    ETHERNET = "Ethernet"


class KinetixFanSpeed(SupersetEnum):
    """Fan speed for ADKinetix detector."""

    OFF = "Off"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class KinetixDriverIO(ADBaseIO):
    """Mirrors the interface provided by ADKinetix/db/ADKinetix.template."""

    trigger_mode: A[SignalRW[KinetixTriggerMode], PvSuffix.rbv("TriggerMode")]
    min_exp_res: A[SignalRW[KinetixMinExpRes], PvSuffix.rbv("MinExpRes")]
    selected_interface: A[SignalR[KinetixCommIntf], PvSuffix("SelectedInterface_RBV")]
    fan_speed: A[SignalRW[KinetixFanSpeed], PvSuffix.rbv("FanSpeed")]

    # Readout settings
    readout_port_idx: A[SignalRW[KinetixReadoutMode], PvSuffix.rbv("ReadoutPortIdx")]
    readout_mode: A[SignalR[str], PvSuffix("ReadoutMode_RBV")]
    readout_mode_valid: A[SignalR[bool], PvSuffix("ReadoutModeValid_RBV")]
    readout_port_name: A[SignalR[str], PvSuffix("ReadoutPortName_RBV")]
    speed_idx: A[SignalRW[KinetixSpeedTableIdx], PvSuffix.rbv("SpeedIdx")]
    gain_idx: A[SignalRW[KinetixSpeedTableIdx], PvSuffix.rbv("GainIdx")]
    speed_desc: A[SignalR[str], PvSuffix("SpeedDesc_RBV")]
    gain_desc: A[SignalR[str], PvSuffix("GainDesc_RBV")]
    apply_readout_mode: A[SignalRW[bool], PvSuffix("ApplyReadoutMode")]


@dataclass
class KinetixTriggerLogic(DetectorTriggerLogic):
    """Trigger logic for ADKinetix detectors."""

    driver: KinetixDriverIO

    def config_sigs(self):
        return {
            self.driver.acquire_time,
            self.driver.trigger_mode,
            self.driver.readout_mode,
            self.driver.min_exp_res,
            self.driver.selected_interface,
            self.driver.fan_speed,
            self.driver.model,
            self.driver.manufacturer,
            self.driver.serial_number,
            self.driver.sdk_version,
        }

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

    async def default_trigger_info(self):
        return await trigger_info_from_num_images(self.driver)


class KinetixDetector(AreaDetector[KinetixDriverIO], Movable):
    """Create an ADKinetix AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
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
        driver_suffix="cam1:",
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = KinetixDriverIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADArmLogic(driver),
            trigger_logic=KinetixTriggerLogic(driver),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )

    @AsyncStatus.wrap
    async def set(self, mode: KinetixReadoutMode):
        """Switch the readout mode of the detector."""

        await self.driver.readout_port_idx.set(mode)

        if not await self.driver.readout_mode_valid.get_value():
            raise RuntimeError(f"Failed to switch to readout mode {mode.name}!")

        await self.driver.apply_readout_mode.set(True)
