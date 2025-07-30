from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scanspec.core import Slice

from ophyd_async.epics.motor import Motor

TICK_S = 0.000001


@dataclass
class Trajectory:
    positions: dict[Motor, np.ndarray]
    velocities: dict[Motor, np.ndarray]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    @classmethod
    def from_slice(
        cls,
        slice: Slice,
    ) -> "Trajectory":
        """Parse a trajectory with no gaps from a slice.

        :param slice: Information about a series of scan frames along a number of axes
        :param ramp_up_duration: Time required to ramp up to speed
        :param ramp_down: Booleon representing if we ramp down or not
        :returns Trajectory: Data class representing our parsed trajectory
        :raises RuntimeError: Slice must have no gaps and a duration array
        """
        if slice.duration is None:
            raise RuntimeError("Slice must have a duration")

        # Check if any gaps other than initial gap.
        if any(slice.gap[1:-1]):
            raise RuntimeError(
                f"Cannot parse trajectory with gaps. Slice has gaps: {slice.gap}"
            )

        scan_size = len(slice)
        scan_axes = slice.axes()

        positions: dict[Motor, npt.NDArray[np.float64]] = {}
        velocities: dict[Motor, npt.NDArray[np.float64]] = {}

        # Initialise arrays
        for axis in scan_axes:
            positions[axis] = np.empty(2 * scan_size, float)
            velocities[axis] = np.empty(2 * scan_size, float)
        durations: npt.NDArray[np.float64] = np.empty(2 * scan_size, float)
        user_programs: npt.NDArray[np.int32] = np.ones(2 * scan_size, float)

        # Set starting points
        start = 0
        for axis in scan_axes:
            positions[axis][start] = slice.lower[axis][start]
            positions[axis][start + 1] = slice.upper[axis][start]

            velocities[axis][start : start + 2] = np.repeat(
                (slice.upper[axis][start] - slice.lower[axis][start])
                / slice.duration[start],
                2,
                axis=0,
            )

        # Fill profile assuming no gaps
        for axis in scan_axes:
            idx = 2
            for point in range(1, len(slice)):
                positions[axis][idx] = slice.midpoints[axis][point]
                positions[axis][idx + 1] = slice.upper[axis][point]
                velocities[axis][idx] = (
                    slice.upper[axis][point] - slice.lower[axis][point]
                ) / slice.duration[point]
                velocities[axis][idx + 1] = (
                    slice.upper[axis][point] - slice.lower[axis][point]
                ) / slice.duration[point]
                idx += 2

        # Half the time per point
        durations = np.repeat(slice.duration / (2 * TICK_S), 2)
        # Full time for initial gap
        durations[start] = int(slice.duration[start] / TICK_S)

        # Returned positions and velocities exclude ramp down state.
        # Returned user programs and durations include ramp down state.
        return cls(
            positions=positions,
            velocities=velocities,
            user_programs=user_programs,
            durations=durations,
        )
