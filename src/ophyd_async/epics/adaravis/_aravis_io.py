from typing import Annotated as A

from ophyd_async.core import OnOff, SignalRW, SubsetEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import PvSuffix


class AravisTriggerSource(SubsetEnum):
    """Which trigger source to use when TriggerMode=On."""

    LINE1 = "Line1"


class AravisDriverIO(adcore.ADBaseIO):
    """Generic Driver supporting all GiGE cameras.

    This mirrors the interface provided by ADAravis/db/aravisCamera.template.
    """

    trigger_mode: A[SignalRW[OnOff], PvSuffix.rbv("TriggerMode")]
    trigger_source: A[SignalRW[AravisTriggerSource], PvSuffix.rbv("TriggerSource")]
