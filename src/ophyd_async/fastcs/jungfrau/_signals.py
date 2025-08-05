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


# These values will need to be changed after https://github.com/DiamondLightSource/FastCS/issues/175
class JungfrauTriggerMode(StrictEnum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class DetectorStatus(StrictEnum):
    IDLE = "IDLE"
    ERROR = "ERROR"
    WAITING = "WAITING"
    RUN_FINISHED = "RUN_FINISHED"
    TRANSMITTING = "TRANSMITTING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


JUNGFRAU_TRIGGER_MODE_MAP = {
    DetectorTrigger.EDGE_TRIGGER: JungfrauTriggerMode.EXTERNAL,
    DetectorTrigger.INTERNAL: JungfrauTriggerMode.INTERNAL,
}


class JungfrauDriverIO(Device):
    """Contains signals for handling IO on the Jungfrau detector."""

    exposure_time: SignalRW[float]  # in s

    period_between_frames: SignalRW[float]  # in s

    # Sets the delay for the beginning of the exposure time after
    # trigger input
    delay_after_trigger: SignalRW[float]  # in s

    # frames per trigger
    frames_per_acq: SignalRW[NonNegativeInt]

    acquisition_start: SignalX

    acquisition_stop: SignalX
    bit_depth: SignalR[int]
    trigger_mode: SignalRW[JungfrauTriggerMode]
    detector_status: SignalR[DetectorStatus]

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))
