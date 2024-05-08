from enum import Enum

from ophyd_async.epics.signal.signal import epics_signal_rw_rbv

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
    def __init__(self, prefix: str, name: str = "") -> None:
        # self.pixel_format = epics_signal_rw_rbv(PixelFormat, prefix + "PixelFormat")
        self.convert_format = epics_signal_rw_rbv(
            VimbaConvertFormat, prefix + "ConvertPixelFormat"
        )  # Pixel format of data outputted to AD
        self.trig_source = epics_signal_rw_rbv(
            VimbaTriggerSource, prefix + "TriggerSource"
        )
        self.trigger_mode = epics_signal_rw_rbv(VimbaOnOff, prefix + "TriggerMode")
        self.overlap = epics_signal_rw_rbv(VimbaOverlap, prefix + "TriggerOverlap")
        self.expose_mode = epics_signal_rw_rbv(
            VimbaExposeOutMode, prefix + "ExposureMode"
        )
        super().__init__(prefix, name)
