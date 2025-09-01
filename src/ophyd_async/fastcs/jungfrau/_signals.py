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


class JungfrauTriggerMode(StrictEnum):
    INTERNAL = "Internal"

    # Detector waits for external trigger to start frame series, but still
    # controls exposure time and frame period internally
    EXTERNAL = "External"


class DetectorStatus(StrictEnum):
    IDLE = "Idle"
    ERROR = "Error"
    WAITING = "Waiting"
    RUN_FINISHED = "RunFinished"
    TRANSMITTING = "Transmitting"
    RUNNING = "Running"
    STOPPED = "Stopped"


class GainMode(StrictEnum):
    DYNAMIC = "Dynamic"
    FORCE_SWITCH_G1 = "ForceSwitchG1"
    FORCE_SWITCH_G2 = "ForceSwitchG2"
    FIX_G1 = "FixG1"
    FIX_G2 = "FixG2"
    FIX_G0 = "FixG0"


JUNGFRAU_TRIGGER_MODE_MAP = {
    DetectorTrigger.EDGE_TRIGGER: JungfrauTriggerMode.EXTERNAL,
    DetectorTrigger.INTERNAL: JungfrauTriggerMode.INTERNAL,
}


class JungfrauDriverIO(Device):
    """Contains signals for handling IO on the Jungfrau detector."""

    exposure_time: SignalRW[float]  # in s

    # Includes deadtime
    period_between_frames: SignalRW[float]  # in s

    # Sets the delay for the beginning of the exposure time after
    # trigger input
    delay_after_trigger: SignalRW[float]  # in s

    # frames per trigger
    frames_per_acq: SignalRW[NonNegativeInt]

    gain_mode: SignalRW[GainMode]

    acquisition_start: SignalX

    acquisition_stop: SignalX
    bit_depth: SignalR[int]
    trigger_mode: SignalRW[JungfrauTriggerMode]
    detector_status: SignalR[DetectorStatus]

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))
