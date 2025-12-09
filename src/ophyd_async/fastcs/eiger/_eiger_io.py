from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    SignalX,
    StrictEnum,
)


class EigerTriggerMode(StrictEnum):
    INTERNAL = "ints"
    EDGE = "exts"
    GATE = "exte"


class EigerMonitorIO(Device):
    pass


class EigerStreamIO(Device):
    pass


class EigerDetectorIO(Device):
    bit_depth_image: SignalR[int]
    state: SignalR[str]
    count_time: SignalRW[float]
    frame_time: SignalRW[float]
    nimages: SignalRW[int]
    ntrigger: SignalRW[int]
    nexpi: SignalRW[int]
    trigger_mode: SignalRW[str]
    roi_mode: SignalRW[str]
    photon_energy: SignalRW[float]
    beam_center_x: SignalRW[float]
    beam_center_y: SignalRW[float]
    detector_distance: SignalRW[float]
    omega_start: SignalRW[float]
    omega_increment: SignalRW[float]
    arm: SignalX
    disarm: SignalX
    trigger: SignalX
