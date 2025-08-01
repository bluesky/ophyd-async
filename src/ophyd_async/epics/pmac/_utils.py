from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scanspec.core import Slice

from ophyd_async.core import error_if_none
from ophyd_async.epics.motor import Motor

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001


@dataclass
class Trajectory:
    positions: dict[Motor, np.ndarray]
    velocities: dict[Motor, np.ndarray]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    @classmethod
    def from_slice(cls, slice: Slice[Motor], ramp_up_time: float) -> Trajectory:
        """Parse a trajectory with no gaps from a slice.

        :param slice: Information about a series of scan frames along a number of axes
        :param ramp_up_duration: Time required to ramp up to speed
        :param ramp_down: Booleon representing if we ramp down or not
        :returns Trajectory: Data class representing our parsed trajectory
        :raises RuntimeError: Slice must have no gaps and a duration array
        """
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")

        # Check if any gaps other than initial gap.
        if any(slice.gap[1:]):
            raise RuntimeError(
                f"Cannot parse trajectory with gaps. Slice has gaps: {slice.gap}"
            )

        scan_size = len(slice)
        motors = slice.axes()

        positions: dict[Motor, npt.NDArray[np.float64]] = {}
        velocities: dict[Motor, npt.NDArray[np.float64]] = {}

        # Initialise arrays
        positions = {motor: np.empty(2 * scan_size + 1, float) for motor in motors}
        velocities = {motor: np.empty(2 * scan_size + 1, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(2 * scan_size + 1, float)
        user_programs: npt.NDArray[np.int32] = np.ones(2 * scan_size + 1, float)
        user_programs[-1] = 8

        # Ramp up time for start of collection window
        durations[0] = int(ramp_up_time / TICK_S)
        # Half the time per point
        durations[1:] = np.repeat(slice_duration / (2 * TICK_S), 2)

        # Fill profile assuming no gaps
        # Excluding starting points, we begin at our next frame
        half_durations = slice_duration / 2
        for motor in motors:
            # Set the first position to be lower bound, then
            # alternate mid and upper as the upper and lower
            # bounds of neighbouring points are the same as gap is false
            positions[motor][0] = slice.lower[motor][0]
            positions[motor][1::2] = slice.midpoints[motor]
            positions[motor][2::2] = slice.upper[motor]
            # For velocities we will need the relative distances
            mid_to_upper_velocities = (
                slice.upper[motor] - slice.midpoints[motor]
            ) / half_durations
            lower_to_mid_velocities = (
                slice.midpoints[motor] - slice.lower[motor]
            ) / half_durations
            # First velocity is the lower -> mid of first point
            velocities[motor][0] = lower_to_mid_velocities[0]
            # For the midpoints, we take the average of the
            # lower -> mid and mid-> upper velocities of the same point
            velocities[motor][1::2] = (
                lower_to_mid_velocities + mid_to_upper_velocities
            ) / 2
            # For the upper points, we need to take the average of the
            # mid -> upper velocity of the previous point and
            # lower -> mid velocity of the current point
            velocities[motor][2:-1:2] = (
                mid_to_upper_velocities[:-1] + lower_to_mid_velocities[1:]
            ) / 2
            # For the last velocity take the mid to upper velocity
            velocities[motor][-1] = mid_to_upper_velocities[-1]

        return cls(
            positions=positions,
            velocities=velocities,
            user_programs=user_programs,
            durations=durations,
        )
