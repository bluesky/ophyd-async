import numpy as np
import numpy.typing as npt
from scanspec.core import Slice

from ophyd_async.epics.motor import Motor


class PmacMotorInfo:
    def __init__(self, cs_port, cs_number, motor_cs_index, motor_acceleration_rate):
        self.cs_port: str = cs_port
        self.cs_number: int = cs_number
        self.motor_cs_index: dict[Motor, int] = motor_cs_index
        self.motor_acceleration_rate: dict[Motor, float] = motor_acceleration_rate


def calculate_ramp_position_and_duration(
    slice: Slice, motor_info: PmacMotorInfo, is_up: bool
) -> tuple[dict[Motor, float], float]:
    scan_axes = slice.axes()
    scan_size = len(slice)
    assert slice.duration is not None  # noqa: S101
    gaps = _calculate_gaps(slice)
    if not gaps[0]:
        gaps = np.delete(gaps, 0)

    positions: dict[int, npt.NDArray[np.float64]] = {}
    velocities: dict[int, npt.NDArray[np.float64]] = {}

    # Initialise positions and velocities arrays
    for axis in scan_axes:
        cs_index = motor_info.motor_cs_index[axis]
        positions[cs_index] = np.empty(
            2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.float64
        )
        velocities[cs_index] = np.empty(
            2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.float64
        )

    # Get starting points
    for axis in scan_axes:
        cs_index = motor_info.motor_cs_index[axis]
        positions[cs_index][0] = slice.lower[axis][0]
        positions[cs_index][1] = slice.upper[axis][0]
        velocities[cs_index][0:2] = np.repeat(
            (slice.upper[axis][0] - slice.lower[axis][0] / slice.duration[0]), 2, axis=0
        )

    pass


def _calculate_gaps(slice: Slice):
    inds = np.argwhere(slice.gap)
    if len(inds) == 0:
        return [len(slice)]
    else:
        return inds
