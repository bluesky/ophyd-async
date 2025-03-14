from typing import Annotated as A

from ophyd_async.core import SignalRW, StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import PvSuffix


class KinetixTriggerMode(StrictEnum):
    """Trigger mode for ADKinetix detector."""

    INTERNAL = "Internal"
    EDGE = "Rising Edge"
    GATE = "Exp. Gate"


class KinetixReadoutMode(StrictEnum):
    """Readout mode for ADKinetix detector."""

    SENSITIVITY = 1
    SPEED = 2
    DYNAMIC_RANGE = 3
    SUB_ELECTRON = 4


class KinetixDriverIO(adcore.ADBaseIO):
    """Mirrors the interface provided by ADKinetix/db/ADKinetix.template."""

    trigger_mode: A[SignalRW[KinetixTriggerMode], PvSuffix("TriggerMode")]
    readout_port_idx: A[SignalRW[KinetixReadoutMode], PvSuffix("ReadoutPortIdx")]
