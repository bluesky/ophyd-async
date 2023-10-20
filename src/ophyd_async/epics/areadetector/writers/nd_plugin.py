from ophyd_async.core import Device
from ophyd_async.epics.signal import epics_signal_rw

from ..utils import ad_r


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = ad_r(int, prefix + "UniqueId")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        super().__init__(name)


class NDPluginBase(NDArrayBase):
    pass


class NDPluginStats(NDPluginBase):
    pass
