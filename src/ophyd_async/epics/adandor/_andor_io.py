from typing import Annotated as A

from ophyd_async.core import SignalR, SignalRW, StrictEnum, SubsetEnum
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


class Andor2DataType(SubsetEnum):
    UINT16 = "UInt16"
    UINT32 = "UInt32"
    FLOAT32 = "Float32"
    FLOAT64 = "Float64"


class Andor2DriverIO(adcore.ADBaseIO):
    """Driver for andor model:DU897_BV as deployed on p99.

    This mirrors the interface provided by AdAndor/db/andor.template.
    https://github.com/areaDetector/ADAndor/blob/master/andorApp/Db/andorCCD.template
    """

    trigger_mode: A[SignalRW[Andor2TriggerMode], PvSuffix.rbv("TriggerMode")]
    andor_accumulate_period: A[SignalR[float], PvSuffix("AndorAccumulatePeriod_RBV")]
