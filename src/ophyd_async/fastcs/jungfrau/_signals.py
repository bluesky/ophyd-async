from enum import StrEnum

from pydantic import NonNegativeInt

from ophyd_async.core import (
    DetectorTrigger,
    Device,
    SignalR,
    SignalRW,
    SignalX,
    StrictEnum,
)
from ophyd_async.fastcs.core import fastcs_connector


class JungfrauTriggerMode(StrEnum):
    # according to https://rtd.xfel.eu/docs/jungfrau-detector-documentation/en/latest/general_introduction.html
    # we have autotrigger mode and external trigger mode
    EXTERNAL = "TRIGGER_EXPOSURE"
    AUTO = "AUTO_TIMING"
    # Got these names from the slsdet module. Not sure if it's strenum or intenum though


JUNGFRAU_TRIGGER_MODE_MAP = {
    DetectorTrigger.EDGE_TRIGGER: JungfrauTriggerMode.EXTERNAL,
    DetectorTrigger.INTERNAL: JungfrauTriggerMode.AUTO,
}


# Used for all SLS detectors
class DetectorStatus(StrictEnum):
    IDLE = "IDLE"
    ERROR = "ERROR"
    WAITING = "WAITING"
    RUN_FINISHED = "RUN_FINISHED"
    TRANSMITTING = "TRANSMITTING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class JungfrauDriverIO(Device):
    """Contains signals for handling IO on the Jungfrau detector."""

    exposure_time: SignalRW[float]  # in s

    # This is 1/frame rate
    period_between_frames: SignalRW[float]  # in s

    # Sets the delay for the beginning of the exposure time after
    # trigger input
    delay_after_trigger: SignalRW[float]  # in s

    # frames per trigger
    frames_per_acq: SignalRW[NonNegativeInt]

    # TODO Signals below this point need adding to fastcs

    # bit depth
    bit_depth: SignalR[
        int
    ]  # TODO need to add this signal to the fast-cs repo. The JF driver name
    # for this signal is "dr" (for dynamic range)

    # TODO driver name here is called "timing"
    trigger_mode: SignalRW[JungfrauTriggerMode]

    # Start is "start the triggering chain", acquire is just "take one image" (I think)
    start: SignalX

    acquisition_stop: SignalX

    # TODO Change this in fast-cs from a string to enum signal
    detector_status: SignalR[DetectorStatus]

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))
