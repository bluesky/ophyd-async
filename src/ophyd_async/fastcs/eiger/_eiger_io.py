from ophyd_async.core import Device, SignalR, SignalRW, SignalW, StrictEnum


class EigerTriggerMode(StrictEnum):
    INTERNAL = "ints"
    EDGE = "exts"
    GATE = "exte"


class EigerDriverIO(Device):
    """Contains signals for handling IO on the Eiger detector."""

    bit_depth: SignalR[int]
    stale_parameters: SignalR[bool]
    state: SignalR[str]
    acquire_time: SignalRW[float]
    acquire_period: SignalRW[float]
    num_images: SignalRW[int]
    trigger_mode: SignalRW[str]
    arm: SignalW[int]
    disarm: SignalW[int]
    photon_energy: SignalRW[float]
