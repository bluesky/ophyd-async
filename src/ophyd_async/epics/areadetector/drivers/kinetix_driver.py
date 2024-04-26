from enum import Enum

from ..utils import ad_rw
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
        # self.pixel_format = ad_rw(PixelFormat, prefix + "PixelFormat")
        self.trigger_mode = ad_rw(KinetixTriggerMode, prefix + "TriggerMode")
        self.mode = ad_rw(KinetixReadoutMode, prefix + "ReadoutPortIdx")
        super().__init__(prefix, name)
