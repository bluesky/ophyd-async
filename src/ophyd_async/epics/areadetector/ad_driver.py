from ophyd_async.core import Device

from ..signal.signal import epics_signal_rw
from .utils import ImageMode, ad_r, ad_rw


class ADDriver(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.acquire = ad_rw(bool, prefix + "Acquire")
        self.acquire_time = ad_rw(float, prefix + "AcquireTime")
        self.num_images = ad_rw(int, prefix + "NumImages")
        self.image_mode = ad_rw(ImageMode, prefix + "ImageMode")
        self.array_counter = ad_rw(int, prefix + "ArrayCounter")
        self.array_size_x = ad_r(int, prefix + "ArraySizeX")
        self.array_size_y = ad_r(int, prefix + "ArraySizeY")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")
