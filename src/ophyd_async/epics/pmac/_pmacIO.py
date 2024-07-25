import numpy as np
import numpy.typing as npt
from bluesky.protocols import Flyable, Preparable

from ophyd_async.core import DeviceVector, StandardReadable, SubsetEnum

from ..signal.signal import epics_signal_r, epics_signal_rw


class Pmac(StandardReadable, Flyable, Preparable):
    """Device that moves a PMAC Motor record"""

    def __init__(self, prefix: str, cs="", name="") -> None:
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
        cs_names_enum = SubsetEnum[cs]
        self.profile_cs_name = epics_signal_rw(cs_names_enum, prefix + ":ProfileCsName")
        self.profile_calc_vel = epics_signal_rw(bool, prefix + ":ProfileCalcVel")
