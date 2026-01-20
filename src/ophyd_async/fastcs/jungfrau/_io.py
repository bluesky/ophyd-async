from pydantic import NonNegativeInt

from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    SignalX,
    StrictEnum,
)


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

    # Use with caution - this may damage the detector
    FIX_G0 = "FixG0"


class PedestalMode(StrictEnum):
    ON = "On"
    OFF = "Off"


class AcquisitionType(StrictEnum):
    STANDARD = "Standard"
    PEDESTAL = "Pedestal"


class JungfrauDriverIO(Device):
    """Contains signals for handling IO on the Jungfrau detector."""

    exposure_time: SignalRW[float]  # in s

    # Includes deadtime
    period_between_frames: SignalRW[float]  # in s

    # Sets the delay for the beginning of the exposure time after
    # trigger input
    delay_after_trigger: SignalRW[float]  # in s

    # In internal trigger mode, this is frames per trigger. In external trigger mode,
    # this is frames per overall acquisition. In pedestal mode, this signal is not set.
    frames_per_acq: SignalRW[NonNegativeInt]

    pedestal_mode_state: SignalRW[PedestalMode]
    pedestal_mode_frames: SignalRW[NonNegativeInt]
    pedestal_mode_loops: SignalRW[NonNegativeInt]

    gain_mode: SignalRW[GainMode]

    acquisition_start: SignalX

    acquisition_stop: SignalX
    bit_depth: SignalR[int]
    trigger_mode: SignalRW[JungfrauTriggerMode]
    detector_status: SignalR[DetectorStatus]
