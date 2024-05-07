from enum import Enum

from ophyd_async.epics.signal.signal import epics_signal_rw_rbv

from .ad_base import ADBase


class PilatusTriggerMode(str, Enum):
    internal = "Internal"
    ext_enable = "Ext. Enable"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class PilatusDriver(ADBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(
            PilatusTriggerMode, prefix + "TriggerMode_RBV"
        )
        super().__init__(prefix, name)
