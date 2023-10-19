from ophyd_async.core import Device
from typing import Tuple, Dict

from ..utils import ad_r


class NDPlugin(Device):
    pass


class NDPluginStats(NDPlugin):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.unique_id = ad_r(int, prefix + "UniqueId")

