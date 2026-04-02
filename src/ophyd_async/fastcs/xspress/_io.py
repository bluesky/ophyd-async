from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    SignalX,
    StrictEnum,
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
    trigger_mode: SignalRW[str]
    acquisition_complete: SignalR[bool]
    start_acquisition: SignalX
    stop_acquisition: SignalX
    bit_depth_image: SignalR[int]
