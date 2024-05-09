from enum import Enum

from ophyd_async.epics.signal.signal import epics_signal_rw_rbv

from .ad_base import ADBase


class KinetixTriggerMode(str, Enum):
    internal = "Internal"
    edge = "Rising Edge"
    gate = "Exp. Gate"


class KinetixReadoutMode(str, Enum):
    sensitivity = 1
    speed = 2
    dynamic_range = 3


class KinetixDriver(ADBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        # self.pixel_format = epics_signal_rw_rbv(PixelFormat, prefix + "PixelFormat")
        self.trigger_mode = epics_signal_rw_rbv(
            KinetixTriggerMode, prefix + "TriggerMode"
        )
        self.mode = epics_signal_rw_rbv(KinetixReadoutMode, prefix + "ReadoutPortIdx")
        super().__init__(prefix, name)
