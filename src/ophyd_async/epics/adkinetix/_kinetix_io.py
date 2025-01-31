from ophyd_async.core import StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import epics_signal_rw_rbv


class KinetixTriggerMode(StrictEnum):
    INTERNAL = "Internal"
    EDGE = "Rising Edge"
    GATE = "Exp. Gate"


class KinetixReadoutMode(StrictEnum):
    SENSITIVITY = 1
    SPEED = 2
    DYNAMIC_RANGE = 3
    SUB_ELECTRON = 4


class KinetixDriverIO(adcore.ADBaseIO):
    """This mirrors the interface provided by ADKinetix/db/ADKinetix.template."""

    def __init__(self, prefix: str, name: str = "") -> None:
        # self.pixel_format = epics_signal_rw_rbv(PixelFormat, prefix + "PixelFormat")
        self.trigger_mode = epics_signal_rw_rbv(
            KinetixTriggerMode, prefix + "TriggerMode"
        )
        self.readout_port_idx = epics_signal_rw_rbv(
            KinetixReadoutMode, prefix + "ReadoutPortIdx"
        )
        super().__init__(prefix, name=name)
