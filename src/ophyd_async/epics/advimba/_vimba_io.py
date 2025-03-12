from typing import Annotated as A

from ophyd_async.core import SignalRW, StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import PvSuffix


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

    convert_pixel_format: A[
        SignalRW[VimbaConvertFormat], PvSuffix("ConvertPixelFormat")
    ]
    trigger_source: A[SignalRW[VimbaTriggerSource], PvSuffix("TriggerSource")]
    trigger_mode: A[SignalRW[VimbaOnOff], PvSuffix("TriggerMode")]
    trigger_overlap: A[SignalRW[VimbaOverlap], PvSuffix("TriggerOverlap")]
    exposure_mode: A[SignalRW[VimbaExposeOutMode], PvSuffix("ExposureMode")]
