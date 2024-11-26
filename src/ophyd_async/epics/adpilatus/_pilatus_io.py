from ophyd_async.core import StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw_rbv


class PilatusTriggerMode(StrictEnum):
    INTERNAL = "Internal"
    EXT_ENABLE = "Ext. Enable"
    EXT_TRIGGER = "Ext. Trigger"
    MULT_TRIGGER = "Mult. Trigger"
    ALIGNMENT = "Alignment"


class PilatusDriverIO(adcore.ADBaseIO):
    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(
            PilatusTriggerMode, prefix + "TriggerMode"
        )
        self.armed = epics_signal_r(bool, prefix + "Armed")
        super().__init__(prefix, name)
