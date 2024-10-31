import numpy as np
import numpy.typing as npt

from ophyd_async.core import DeviceVector, StandardReadable
from ophyd_async.epics import motor

from ..signal import epics_signal_r, epics_signal_rw


class Pmac(StandardReadable):
    """Device that moves a PMAC Motor record"""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.time_array = epics_signal_rw(
            npt.NDArray[np.float64], prefix + ":ProfileTimeArray"
        )
        cs_letters = "ABCUVWXYZ"
        # 1 indexed CS axes so we can index into them from the compound motor input link
        self.positions = DeviceVector(
            {
                i + 1: epics_signal_rw(
                    npt.NDArray[np.float64], f"{prefix}:{letter}:Positions"
                )
                for i, letter in enumerate(cs_letters)
            }
        )
        self.use_axis = DeviceVector(
            {
                i + 1: epics_signal_rw(bool, f"{prefix}:{letter}:UseAxis")
                for i, letter in enumerate(cs_letters)
            }
        )
        self.velocities = DeviceVector(
            {
                i + 1: epics_signal_rw(
                    npt.NDArray[np.float64], f"{prefix}:{letter}:Velocities"
                )
                for i, letter in enumerate(cs_letters)
            }
        )
        self.points_to_build = epics_signal_rw(int, prefix + ":ProfilePointsToBuild")
        self.build_profile = epics_signal_rw(bool, prefix + ":ProfileBuild")
        self.execute_profile = epics_signal_rw(bool, prefix + ":ProfileExecute")
        self.scan_percent = epics_signal_r(float, prefix + ":TscanPercent_RBV")
        self.profile_abort = epics_signal_rw(bool, prefix + ":ProfileAbort")
        self.profile_cs_name = epics_signal_rw(str, prefix + ":ProfileCsName")
        self.profile_calc_vel = epics_signal_rw(bool, prefix + ":ProfileCalcVel")

        super().__init__(name=name)


class PmacMotor(motor.Motor):
    """Device that moves a PMAC Motor record"""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.cs_axis = epics_signal_r(str, f"{prefix}:CsAxis_RBV")
        self.cs_port = epics_signal_r(str, f"{prefix}:CsPort_RBV")
        super().__init__(prefix=prefix, name=name)
