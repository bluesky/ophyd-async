from enum import Enum

from ..utils import ad_rw
from .ad_base import ADBase


class PilatusTriggerMode(str, Enum):
    internal = "Internal"
    ext_enable = "Ext. Enable"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class PilatusDriver(ADBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = ad_rw(PilatusTriggerMode, prefix + "TriggerMode")
        super().__init__(prefix, name)
