from enum import Enum

from ophyd_async.core import AsyncStatus, Device
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw_rbv, epics_signal_x


class EigerTriggerMode(str, Enum):
    internal = "ints"
    edge = "exts"
    gate = "exte"


class PhotonEnergy(Device):
    """Changing photon energy takes some time so only do so if the current energy is
    outside the tolerance."""

    def __init__(self, prefix, tolerance=0.1, name: str = "") -> None:
        self._photon_energy = epics_signal_rw_rbv(float, f"{prefix}PhotonEnergy")
        self.tolerance = tolerance
        super().__init__(name)

    @AsyncStatus.wrap
    async def set(self, value):
        current_energy = await self._photon_energy.get_value()
        if abs(current_energy - value) > self.tolerance:
            await self._photon_energy.set(value)


class EigerDriverIO(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.bit_depth = epics_signal_r(int, f"{prefix}BitDepthReadout")
        self.stale_parameters = epics_signal_r(bool, f"{prefix}StaleParameters")
        self.state = epics_signal_r(str, f"{prefix}DetectorState")
        self.roi_mode = epics_signal_rw_rbv(str, f"{prefix}RoiMode")

        self.acquire_time = epics_signal_rw_rbv(float, f"{prefix}CountTime")
        self.acquire_period = epics_signal_rw_rbv(float, f"{prefix}FrameTime")

        self.num_images = epics_signal_rw_rbv(int, f"{prefix}Nimages")
        self.num_triggers = epics_signal_rw_rbv(int, f"{prefix}Ntrigger")

        # Ideally this will be a EigerTriggerMode, see https://github.com/DiamondLightSource/eiger-fastcs/issues/43
        self.trigger_mode = epics_signal_rw_rbv(str, f"{prefix}TriggerMode")

        self.arm = epics_signal_x(f"{prefix}Arm")
        self.disarm = epics_signal_x(f"{prefix}Disarm")
        self.abort = epics_signal_x(f"{prefix}Abort")

        self.beam_centre_x = epics_signal_rw_rbv(float, f"{prefix}BeamCenterX")
        self.beam_centre_y = epics_signal_rw_rbv(float, f"{prefix}BeamCenterY")

        self.det_distance = epics_signal_rw_rbv(float, f"{prefix}DetectorDistance")
        self.omega_start = epics_signal_rw_rbv(float, f"{prefix}OmegaStart")
        self.omega_increment = epics_signal_rw_rbv(float, f"{prefix}OmegaIncrement")

        self.photon_energy = PhotonEnergy(prefix)

        super().__init__(name)
