from enum import Enum

from ..utils import ad_rw
from .ad_base import ADBase


class VimbaPixelFormat(str, Enum):
    internal = "Mono8"
    ext_enable = "Mono12"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class VimbaConvertFormat(str, Enum):
    none = "None"
    mono8 = "Mono8"
    mono16 = "Mono16"
    rgb8 = "RGB8"
    rgb16 = "RGB16"


class VimbaTriggerSource(str, Enum):
    freerun = "Freerun"
    line1 = "Line1"
    line2 = "Line2"
    fixed_rate = "FixedRate"
    software = "Software"
    action0 = "Action0"
    action1 = "Action1"


class VimbaOverlap(str, Enum):
    off = "Off"
    prev_frame = "PreviousFrame"


class VimbaOnOff(str, Enum):
    on = "On"
    off = "Off"


class VimbaExposeOutMode(str, Enum):
    timed = "Timed"  # Use ExposureTime PV
    trigger_width = "TriggerWidth"  # Expose for length of high signal


class VimbaDriver(ADBase):
    def __init__(self, prefix: str) -> None:
        # self.pixel_format = ad_rw(PixelFormat, prefix + "PixelFormat")
        self.convert_format = ad_rw(
            VimbaConvertFormat, prefix + "ConvertPixelFormat"
        )  # Pixel format of data outputted to AD
        self.trig_source = ad_rw(VimbaTriggerSource, prefix + "TriggerSource")
        self.trigger_mode = ad_rw(VimbaOnOff, prefix + "TriggerMode")
        self.overlap = ad_rw(VimbaOverlap, prefix + "TriggerOverlap")
        self.expose_mode = ad_rw(VimbaExposeOutMode, prefix + "ExposureMode")
        super().__init__(prefix)
