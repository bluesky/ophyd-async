from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    SignalW,
    StrictEnum,
)
from ophyd_async.fastcs.core import fastcs_connector


class EigerTriggerMode(StrictEnum):
    INTERNAL = "ints"
    EDGE = "exts"
    GATE = "exte"


class EigerDriverIO(Device):
    """Contains signals for handling IO on the Eiger detector."""

    bit_depth_readout: SignalR[int]
    stale_parameters: SignalR[bool]
    state: SignalR[str]
    count_time: SignalRW[float]
    frame_time: SignalRW[float]
    nimages: SignalRW[int]
    trigger_mode: SignalRW[str]
    arm: SignalW[int]
    disarm: SignalW[int]
    photon_energy: SignalRW[float]
    beam_center_x: SignalRW[float]
    beam_center_y: SignalRW[float]
    detector_distance: SignalRW[float]
    omega_start: SignalRW[float]
    omega_increment: SignalRW[float]

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))
