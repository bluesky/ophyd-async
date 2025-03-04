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

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))
