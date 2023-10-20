from enum import Enum

from ..utils import ad_rw
from .ad_driver import ADDriver


class TriggerSource(Enum):
    freerun = "Freerun"
    line_1 = "Line1"
    line_2 = "Line2"
    fixed_rate = "FixedRate"
    software = "Software"


class TriggerMode(Enum):
    on = "On"
    off = "Off"


class ADAravisDriver(ADDriver):
    def __init__(self, prefix: str) -> None:
        self.trigger_mode = ad_rw(TriggerMode, prefix + "TriggerMode")
        self.trigger_source = ad_rw(TriggerSource, prefix + "TriggerMode")
        super().__init__(prefix)
