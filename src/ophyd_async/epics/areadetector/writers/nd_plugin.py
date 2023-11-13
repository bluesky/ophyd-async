from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import epics_signal_rw

from ..utils import ad_r, ad_rw


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = ad_r(int, prefix + "UniqueId")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        super().__init__(name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = ad_rw(str, prefix + "NDArrayPort")
        self.enable_callback = ad_rw(Callback, prefix + "EnableCallbacks")
        super().__init__(prefix, name)


class NDPluginStats(NDPluginBase):
    pass
