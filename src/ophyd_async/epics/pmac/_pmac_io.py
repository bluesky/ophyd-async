from collections.abc import Sequence

import numpy as np

from ophyd_async.core import Array1D, Device, DeviceVector, StandardReadable
from ophyd_async.epics import motor
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw

CS_LETTERS = "ABCUVWXYZ"


class PmacTrajectoryIO(StandardReadable):
    """Device that moves a PMAC Motor record."""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.time_array = epics_signal_rw(
            Array1D[np.float64], prefix + "ProfileTimeArray"
        )
        self.user_array = epics_signal_rw(Array1D[np.int32], prefix + "UserArray")
        # 1 indexed CS axes so we can index into them from the compound motor input link
        self.positions = DeviceVector(
            {
                i + 1: epics_signal_rw(
                    Array1D[np.float64], f"{prefix}{letter}:Positions"
                )
                for i, letter in enumerate(CS_LETTERS)
            }
        )
        self.use_axis = DeviceVector(
            {
                i + 1: epics_signal_rw(bool, f"{prefix}{letter}:UseAxis")
                for i, letter in enumerate(CS_LETTERS)
            }
        )
        self.velocities = DeviceVector(
            {
                i + 1: epics_signal_rw(
                    Array1D[np.float64], f"{prefix}{letter}:Velocities"
                )
                for i, letter in enumerate(CS_LETTERS)
            }
        )
        self.points_to_build = epics_signal_rw(int, prefix + "ProfilePointsToBuild")
        self.build_profile = epics_signal_rw(bool, prefix + "ProfileBuild")
        self.execute_profile = epics_signal_rw(bool, prefix + "ProfileExecute")
        self.scan_percent = epics_signal_r(float, prefix + "TscanPercent_RBV")
        self.abort_profile = epics_signal_rw(bool, prefix + "ProfileAbort")
        self.profile_cs_name = epics_signal_rw(str, prefix + "ProfileCsName")
        self.calculate_velocities = epics_signal_rw(bool, prefix + "ProfileCalcVel")

        super().__init__(name=name)


class PmacAxisAssignmentIO(Device):
    """A Device that (direct) moves a PMAC Coordinate System Motor.

    Note that this does not go through a motor record.
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.cs_axis_letter = epics_signal_r(str, f"{prefix}CsAxis_RBV")
        self.cs_port = epics_signal_r(str, f"{prefix}CsPort_RBV")
        self.cs_number = epics_signal_r(int, f"{prefix}CsRaw_RBV")
        super().__init__(name=name)


class PmacCoordIO(Device):
    """A Device that represents a Pmac Coordinate System."""

    def __init__(self, prefix: str, name: str = "") -> None:
        self.defer_moves = epics_signal_rw(bool, f"{prefix}DeferMoves")
        self.cs_port = epics_signal_r(str, f"{prefix}Port")
        self.cs_axis_setpoint = DeviceVector(
            {
                i + 1: epics_signal_rw(np.float64, f"{prefix}M{i + 1}:DirectDemand")
                for i in range(len(CS_LETTERS))
            }
        )
        super().__init__(name=name)


class PmacIO(Device):
    """Device that represents a pmac controller."""

    def __init__(
        self,
        prefix: str,
        raw_motors: Sequence[motor.Motor],
        coord_nums: Sequence[int],
        name: str = "",
    ) -> None:
        motor_prefixes = [motor.motor_egu.source.split(".")[0] for motor in raw_motors]

        self.assignment = DeviceVector(
            {
                i: PmacAxisAssignmentIO(motor_prefix)
                for i, motor_prefix in enumerate(motor_prefixes)
            }
        )

        # Public Look up for motor to axis assignment DeviceVector index

        self.motor_assignment_index = {motor: i for i, motor in enumerate(raw_motors)}

        self.coord = DeviceVector(
            {coord: PmacCoordIO(prefix=f"{prefix}CS{coord}:") for coord in coord_nums}
        )
        # Trajectory PVs have the same prefix as the pmac device
        self.trajectory = PmacTrajectoryIO(prefix)

        super().__init__(name=name)
