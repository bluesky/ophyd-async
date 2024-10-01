from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw_rbv, epics_signal_w


class EigerTriggerMode(str, Enum):
    internal = "ints"
    edge = "exts"
    gate = "exte"


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

        # TODO: Should be EigerTriggerMode enum, see https://github.com/DiamondLightSource/eiger-fastcs/issues/43
        self.trigger_mode = epics_signal_rw_rbv(str, f"{prefix}TriggerMode")

        self.arm = epics_signal_w(int, f"{prefix}Arm")
        self.disarm = epics_signal_w(int, f"{prefix}Disarm")
        self.abort = epics_signal_w(int, f"{prefix}Abort")

        self.beam_centre_x = epics_signal_rw_rbv(float, f"{prefix}BeamCenterX")
        self.beam_centre_y = epics_signal_rw_rbv(float, f"{prefix}BeamCenterY")

        self.det_distance = epics_signal_rw_rbv(float, f"{prefix}DetectorDistance")
        self.omega_start = epics_signal_rw_rbv(float, f"{prefix}OmegaStart")
        self.omega_increment = epics_signal_rw_rbv(float, f"{prefix}OmegaIncrement")

        self.photon_energy = epics_signal_rw_rbv(float, f"{prefix}PhotonEnergy")

        super().__init__(name)
