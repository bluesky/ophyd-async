from enum import Enum

from ..utils import ad_rw
from .ad_base import ADBase


class PixelFormat(str, Enum):
    internal = "Mono8"
    ext_enable = "Mono12"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class ConvertFormat(str, Enum):
    none = "None"
    mono8 = "Mono8"
    mono16 = "Mono16"
    rgb8 = "RGB8"
    rgb16 = "RGB16"


class TriggerSource(str, Enum):
    freerun = "Freerun"
    line1 = "Line1"
    line2 = "Line2"
    fixed_rate = "FixedRate"
    software = "Software"
    action0 = "Action0"
    action1 = "Action1"


class Overlap(str, Enum):
    off = "Off"
    prev_frame = "PreviousFrame"


class OnOff(str, Enum):
    on = "On"
    off = "Off"


class ExposeOutMode(str, Enum):
    timed = "Timed"  # Use ExposureTime PV
    trigger_width = "TriggerWidth"  # Expose for length of high signal


class VimbaDriver(ADBase):
    def __init__(self, prefix: str) -> None:
        # self.pixel_format = ad_rw(PixelFormat, prefix + "PixelFormat")
        self.convert_format = ad_rw(
            ConvertFormat, prefix + "ConvertPixelFormat"
        )  # Pixel format of data outputted to AD
        self.trigger_source = ad_rw(TriggerSource, prefix + "TriggerSource")
        self.trigger_mode = ad_rw(OnOff, prefix + "TriggerMode")
        self.overlap = ad_rw(Overlap, prefix + "TriggerOverlap")
        self.expose_out_mode = ad_rw(ExposeOutMode, prefix + "ExposureMode")
        super().__init__(prefix)
