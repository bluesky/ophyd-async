from typing import Annotated as A

from ophyd_async.core import SignalR, SignalRW, StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import (
    PvSuffix,
)


class Andor2TriggerMode(StrictEnum):
    INTERNAL = "Internal"
    EXT_TRIGGER = "External"
    EXT_START = "External Start"
    EXT_EXPOSURE = "External Exposure"
    EXT_FVP = "External FVP"
    SOFTWARE = "Software"


class Andor2DriverIO(adcore.ADBaseIO):
    """Driver for andor model:DU897_BV as deployed on p99.

    This mirrors the interface provided by AdAndor/db/andor.template.
    https://areadetector.github.io/areaDetector/ADAndor/andorDoc.html
    """

    trigger_mode: A[SignalRW[Andor2TriggerMode], PvSuffix.rbv("TriggerMode")]
    andor_accumulate_period: A[SignalR[float], PvSuffix("AndorAccumulatePeriod_RBV")]
