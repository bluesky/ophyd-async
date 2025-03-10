from typing import Annotated as A

from ophyd_async.core import SignalR, SignalRW, StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import PvSuffix


class PilatusTriggerMode(StrictEnum):
    """Trigger modes for ADPilatus detector."""

    INTERNAL = "Internal"
    EXT_ENABLE = "Ext. Enable"
    EXT_TRIGGER = "Ext. Trigger"
    MULT_TRIGGER = "Mult. Trigger"
    ALIGNMENT = "Alignment"


class PilatusDriverIO(adcore.ADBaseIO):
    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""

    trigger_mode = A[SignalRW[PilatusTriggerMode], PvSuffix.rbv("TriggerMode")]
    armed = A[SignalR[bool], PvSuffix.rbv("Armed")]
