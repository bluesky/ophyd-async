from ophyd_async.core import StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import epics_signal_rw_rbv


class VimbaPixelFormat(StrictEnum):
    INTERNAL = "Mono8"
    EXT_ENABLE = "Mono12"
    EXT_TRIGGER = "Ext. Trigger"
    MULT_TRIGGER = "Mult. Trigger"
    ALIGNMENT = "Alignment"


class VimbaConvertFormat(StrictEnum):
    NONE = "None"
    MONO8 = "Mono8"
    MONO16 = "Mono16"
    RGB8 = "RGB8"
    RGB16 = "RGB16"


class VimbaTriggerSource(StrictEnum):
    """Mode for the source of triggers on the Vimbda."""

    FREERUN = "Freerun"
    LINE1 = "Line1"
    LINE2 = "Line2"
    FIXED_RATE = "FixedRate"
    SOFTWARE = "Software"
    ACTION0 = "Action0"
    ACTION1 = "Action1"


class VimbaOverlap(StrictEnum):
    OFF = "Off"
    PREV_FRAME = "PreviousFrame"


class VimbaOnOff(StrictEnum):
    """On/Off modes on the Vimba detector."""

    ON = "On"
    OFF = "Off"


class VimbaExposeOutMode(StrictEnum):
    """Modes for exposure on the Vimba detector."""

    TIMED = "Timed"  # Use ExposureTime PV
    TRIGGER_WIDTH = "TriggerWidth"  # Expose for length of high signal


class VimbaDriverIO(adcore.ADBaseIO):
    """Mirrors the interface provided by ADVimba/db/vimba.template."""

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
        super().__init__(prefix, name=name)
