from ophyd_async.core import StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.signal import epics_signal_rw_rbv


class VimbaPixelFormat(StrictEnum):
    internal = "Mono8"
    ext_enable = "Mono12"
    ext_trigger = "Ext. Trigger"
    mult_trigger = "Mult. Trigger"
    alignment = "Alignment"


class VimbaConvertFormat(StrictEnum):
    none = "None"
    mono8 = "Mono8"
    mono16 = "Mono16"
    rgb8 = "RGB8"
    rgb16 = "RGB16"


class VimbaTriggerSource(StrictEnum):
    freerun = "Freerun"
    line1 = "Line1"
    line2 = "Line2"
    fixed_rate = "FixedRate"
    software = "Software"
    action0 = "Action0"
    action1 = "Action1"


class VimbaOverlap(StrictEnum):
    off = "Off"
    prev_frame = "PreviousFrame"


class VimbaOnOff(StrictEnum):
    on = "On"
    off = "Off"


class VimbaExposeOutMode(StrictEnum):
    timed = "Timed"  # Use ExposureTime PV
    trigger_width = "TriggerWidth"  # Expose for length of high signal


class VimbaDriverIO(adcore.ADBaseIO):
    """This mirrors the interface provided by ADVimba/db/vimba.template."""

    def __init__(self, prefix: str, name: str = "") -> None:
        # self.pixel_format = epics_signal_rw_rbv(PixelFormat, prefix + "PixelFormat")
        self.convert_pixel_format = epics_signal_rw_rbv(
            VimbaConvertFormat, prefix + "ConvertPixelFormat"
        )  # Pixel format of data outputted to AD
        self.trigger_source = epics_signal_rw_rbv(
            VimbaTriggerSource, prefix + "TriggerSource"
        )
        self.trigger_mode = epics_signal_rw_rbv(VimbaOnOff, prefix + "TriggerMode")
        self.trigger_overlap = epics_signal_rw_rbv(
            VimbaOverlap, prefix + "TriggerOverlap"
        )
        self.exposure_mode = epics_signal_rw_rbv(
            VimbaExposeOutMode, prefix + "ExposureMode"
        )
        super().__init__(prefix, name)
