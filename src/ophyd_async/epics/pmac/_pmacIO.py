import numpy as np
import numpy.typing as npt
from bluesky.protocols import Flyable, Preparable

from ophyd_async.core import StandardReadable

from ..signal.signal import epics_signal_rw


class Pmac(StandardReadable, Flyable, Preparable):
    """Device that moves a PMAC Motor record"""

    def __init__(self, prefix: str, name="") -> None:
        self.timeArray = epics_signal_rw(
            npt.NDArray[np.float64], prefix + ":ProfileTimeArray"
        )
        self.a = epics_signal_rw(npt.NDArray[np.float64], prefix + ":A:Positions")
        self.use_a = epics_signal_rw(bool, prefix + ":A:UseAxis")
        self.a_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":A:Velocities")
        self.b = epics_signal_rw(npt.NDArray[np.float64], prefix + ":B:Positions")
        self.use_b = epics_signal_rw(bool, prefix + ":B:UseAxis")
        self.b_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":B:Velocities")
        self.c = epics_signal_rw(npt.NDArray[np.float64], prefix + ":C:Positions")
        self.use_c = epics_signal_rw(bool, prefix + ":C:UseAxis")
        self.c_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":C:Velocities")
        self.u = epics_signal_rw(npt.NDArray[np.float64], prefix + ":U:Positions")
        self.use_u = epics_signal_rw(bool, prefix + ":U:UseAxis")
        self.u_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":U:Velocities")
        self.v = epics_signal_rw(npt.NDArray[np.float64], prefix + ":V:Positions")
        self.use_v = epics_signal_rw(bool, prefix + ":V:UseAxis")
        self.v_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":V:Velocities")
        self.w = epics_signal_rw(npt.NDArray[np.float64], prefix + ":W:Positions")
        self.use_w = epics_signal_rw(bool, prefix + ":W:UseAxis")
        self.w_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":W:Velocities")
        self.x = epics_signal_rw(npt.NDArray[np.float64], prefix + ":X:Positions")
        self.use_x = epics_signal_rw(bool, prefix + ":X:UseAxis")
        self.x_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":X:Velocities")
        self.y = epics_signal_rw(npt.NDArray[np.float64], prefix + ":Y:Positions")
        self.use_y = epics_signal_rw(bool, prefix + ":Y:UseAxis")
        self.y_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":Y:Velocities")
        self.z = epics_signal_rw(npt.NDArray[np.float64], prefix + ":Z:Positions")
        self.use_z = epics_signal_rw(bool, prefix + ":Z:UseAxis")
        self.z_vel = epics_signal_rw(npt.NDArray[np.float64], prefix + ":Z:Velocities")
