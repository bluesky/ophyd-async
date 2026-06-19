from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    StrictEnum,
    TriggerableCommand,
)


class XspressTriggerMode(StrictEnum):
    SOFTWARE = "0"
    HARDWARE = "1"
    BURST = "2"


class XspressDetectorIO(Device):
    """Driver for Xspress Detector subsystem."""

    state: SignalR[str]
    num_images: SignalRW[int]
    exposure_time: SignalRW[float]
    trigger_mode: SignalRW[int]
    acquisition_complete: SignalR[bool]
    start_acquisition: TriggerableCommand
    stop_acquisition: TriggerableCommand
