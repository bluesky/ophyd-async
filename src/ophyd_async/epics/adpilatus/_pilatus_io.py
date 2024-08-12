from enum import Enum

from ophyd_async.epics import adcore
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw_rbv


class PilatusTriggerMode(str, Enum):
    internal = "Internal"
    ext_enable = "Ext. Enable"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class PilatusDriverIO(adcore.ADBaseIO):
    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(
            PilatusTriggerMode, prefix + "TriggerMode"
        )
        self.armed = epics_signal_r(bool, prefix + "Armed")
        super().__init__(prefix, name)
