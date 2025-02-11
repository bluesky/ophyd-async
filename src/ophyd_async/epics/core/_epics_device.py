from ophyd_async.core import Device

from ._epics_connector import EpicsDeviceConnector
from ._pvi_connector import PviDeviceConnector


class EpicsDevice(Device):
    """Baseclass to allow child signals to be created declaratively."""

    def __init__(self, prefix: str, with_pvi: bool = False, name: str = ""):
        if with_pvi:
            connector = PviDeviceConnector(prefix)
        else:
            connector = EpicsDeviceConnector(prefix)
        super().__init__(name=name, connector=connector)
