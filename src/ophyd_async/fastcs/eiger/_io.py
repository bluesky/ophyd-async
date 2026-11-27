import inspect

from ophyd_async.core import (
    Device,
    DeviceConnector,
    Reference,
    SignalR,
    SignalRW,
    SoftCommandBackend,
    StrictEnum,
    TriggerableCommand,
)


class EigerTriggerMode(StrictEnum):
    INTERNAL = "ints"
    EDGE = "exts"
    GATE = "exte"


class EigerMonitorIO(Device):
    """Driver for Eiger Monitor subsystem.

    This mirrors the interface provided by https://media.dectris.com/SIMPLON_APIReference_v1p6.pdf#page=25
    """

    pass


class EigerStreamIO(Device):
    """Driver for Eiger Stream subsystem.

    This mirrors the interface provided by https://media.dectris.com/SIMPLON_APIReference_v1p6.pdf#page=32
    """

    pass


class HVResetTrigger(TriggerableCommand):
    """The HV reset trigger command.

    The reset trigger only calls back when the reset has completed i.e. after the time
    specified by `hv_reset_duration`. Therefore, this command uses that duration (plus
    5 seconds) as a timeout.
    """

    async def _trigger(self) -> None:
        reset_time = await self.hv_reset_duration().get_value()
        await self.underlying_trigger().trigger(reset_time + 5)

    def __init__(
        self,
        underlying_trigger: Reference[TriggerableCommand],
        hv_reset_duration: Reference[SignalRW[int]],
        name: str = "",
    ):
        command = self._trigger
        sig = inspect.signature(command, eval_str=True)
        backend = SoftCommandBackend(command, sig)
        self.underlying_trigger = underlying_trigger
        self.hv_reset_duration = hv_reset_duration
        super().__init__(backend, timeout=None, name=name)


class EigerDetectorIO(Device):
    """Driver for Eiger Detector subsystem.

    This mirrors the interface provided by https://media.dectris.com/SIMPLON_APIReference_v1p6.pdf#page=17
    """

    bit_depth_image: SignalR[int]
    state: SignalR[str]
    count_time: SignalRW[float]
    frame_time: SignalRW[float]
    nimages: SignalRW[int]
    ntrigger: SignalRW[int]
    nexpi: SignalRW[int] | None
    trigger_mode: SignalRW[str]
    roi_mode: SignalRW[str]
    photon_energy: SignalRW[float]
    beam_center_x: SignalRW[float]
    beam_center_y: SignalRW[float]
    detector_distance: SignalRW[float]
    omega_start: SignalRW[float]
    omega_increment: SignalRW[float]
    arm: TriggerableCommand
    disarm: TriggerableCommand
    trigger_: TriggerableCommand
    hv_reset_duration: SignalRW[int]
    hv_reset_: TriggerableCommand

    def __init__(
        self, name: str = "", connector: DeviceConnector | None = None
    ) -> None:
        super().__init__(name, connector)
        self.hv_reset = HVResetTrigger(
            Reference(self.hv_reset_),
            Reference(self.hv_reset_duration),
        )
