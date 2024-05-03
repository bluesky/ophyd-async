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
        self.acquire = ad_rw(bool, prefix + "Acquire")
        self.array_size_x = ad_r(int, prefix + "ArraySizeX")
        self.array_size_y = ad_r(int, prefix + "ArraySizeY")
        self.array_counter = ad_rw(int, prefix + "ArrayCounter")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")
        super().__init__(name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = ad_rw(str, prefix + "NDArrayPort")
        self.enable_callback = ad_rw(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = ad_rw(int, prefix + "NDArrayAddress")
        self.array_size0 = ad_r(int, prefix + "ArraySize0")
        self.array_size1 = ad_r(int, prefix + "ArraySize1")
        super().__init__(prefix, name)


class NDPluginStats(NDPluginBase):
    pass
