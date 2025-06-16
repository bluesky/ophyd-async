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
    """Driver for the Pilatus pixel array detectors."""

    """This mirrors the interface provided by ADPilatus/db/pilatus.template."""
    """See HTML docs at https://areadetector.github.io/areaDetector/ADPilatus/pilatusDoc.html"""
    trigger_mode: A[SignalRW[PilatusTriggerMode], PvSuffix.rbv("TriggerMode")]
    armed: A[SignalR[bool], PvSuffix("Armed")]
