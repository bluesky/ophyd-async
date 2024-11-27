from ophyd_async.core import StrictEnum
from ophyd_async.epics.adcore import ADBaseDataType, ADBaseIO
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)


class Andor2TriggerMode(StrictEnum):
    INTERNAL = "Internal"
    EXT_TRIGGER = "External"
    EXT_START = "External Start"
    EXT_EXPOSURE = "External Exposure"
    EXT_FVP = "External FVP"
    SOFTWARE = "Software"


class ImageMode(StrictEnum):
    SINGLE = "Single"
    MULTIPLE = "Multiple"
    CONTINUOUS = "Continuous"
    FAST_KINETICS = "Fast Kinetics"


class Andor2DriverIO(ADBaseIO):
    """
    Epics pv for andor model:DU897_BV as deployed on p99
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw(Andor2TriggerMode, prefix + "TriggerMode")
        self.data_type = epics_signal_r(ADBaseDataType, prefix + "DataType_RBV")
        self.accumulate_period = epics_signal_r(
            float, prefix + "AndorAccumulatePeriod_RBV"
        )
        self.image_mode = epics_signal_rw_rbv(ImageMode, prefix + "ImageMode")
        super().__init__(prefix, name=name)
