from typing import Annotated as A

from ophyd_async.core import SignalRW, StrictEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.core import PvSuffix


class VimbaConvertFormat(StrictEnum):
    """Convert pixel format for the Vimba detector."""

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
    """Overlap modes for the Vimba detector."""

    OFF = "Off"
    PREV_FRAME = "PreviousFrame"


class VimbaOnOff(StrictEnum):
    """On/Off modes on the Vimba detector."""

    ON = "On"
    OFF = "Off"


class VimbaExposeOutMode(StrictEnum):
    """Exposure control modes for Vimba detectors."""

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
