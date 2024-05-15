from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.epics.signal.signal import epics_signal_r, epics_signal_rw_rbv


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = epics_signal_r(int, prefix + "UniqueId_RBV")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        super().__init__(name=name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = epics_signal_rw_rbv(str, prefix + "NDArrayPort")
        self.enable_callback = epics_signal_rw_rbv(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = epics_signal_rw_rbv(int, prefix + "NDArrayAddress")
        super().__init__(prefix, name)


class NDPluginStats(NDPluginBase):
    pass
