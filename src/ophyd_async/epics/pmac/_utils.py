from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt
from numpy import float64
from scanspec.core import Slice
from velocity_profile.velocityprofile import VelocityProfile

from ophyd_async.core import error_if_none, gather_dict
from ophyd_async.epics.motor import Motor

from ._pmac_io import CS_LETTERS, PmacIO

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001
MIN_TURNAROUND = 0.002
MIN_INTERVAL = 0.002


class UserProgram(IntEnum):
    COLLECTION_WINDOW = 1  # Period within a collection window
    GAP = 2  # Transition period between collection windows
    END = 8  # Post-scan state


class FillableSegment(Protocol):
    """Protocol for trajectory segments that can insert their data into a trajectory.

    A 'FillableSegment' represents a contiguous portion of a trajectory
    that knows how to:
      - Insert its motor positions and velocities into a '_Trajectory'.
      - Insert its durations and associated user programs into a '_Trajectory'.
      - Report its own length.
    """

    def insert_positions_and_velocities_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
        motor: Motor,
    ) -> None:
        """Insert segment's positions and velocities for a given motor.

        :param index_into_trajectory: Index into the trajectory this segment is inserted
        :param trajectory: Instance of '_Trajectory' that will be populated
        :param motor: Motor we are populating '_Trajectory' for
        """
        pass

    def insert_durations_and_user_programs_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
    ) -> None:
        """Insert segment's durations and user programs.

        :param index_into_trajectory: Index into the trajectory this segment is inserted
        :param trajectory: Instance of '_Trajectory' that will be populated
        """
        pass

    def __len__(self) -> int:
        """Return the number of trajectory points in this segment."""
        ...


class GapSegment:
    def __init__(
        self,
        positions: dict[Motor, np.ndarray],
        velocities: dict[Motor, np.ndarray],
        duration: list[float],
    ):
        """Represents a gap between collection windows in a trajectory.

        :param positions: Motor to gap positions
        :param velocities: Motor to gap velocities
        :param duration: List of time required to achieve gap point
        """
        self.positions = positions
        self.velocities = velocities
        self.duration = duration

    def __len__(self):
        # Gap length is the number of per-axis position points
        # This number is identical for all motors
        # as all motors follow a unified timeline through a gap
        return next(iter(self.positions.values())).shape[0]

    def insert_positions_and_velocities_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
        motor: Motor,
    ):
        """Inserts gap positions and velocities into the trajectory.

        This function will populate a '_Trajectory' with the current 'GapSegment's
        pre-computed positions and velocities for a given motor.
        """
        num_gap_points = self.__len__()
        # Update how many gap points we've added so far
        # Insert gap points into end of collection window
        trajectory.positions[motor][
            index_into_trajectory : index_into_trajectory + num_gap_points
        ] = self.positions[motor]
        trajectory.velocities[motor][
            index_into_trajectory : index_into_trajectory + num_gap_points
        ] = self.velocities[motor]

    def insert_durations_and_user_programs_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
    ) -> None:
        """Inserts gap durations and user programs into the trajectory.

        This function will populate a '_Trajectory' with the current 'GapSegment's
        pre-computed durations and set user programs to 'UserProgram.GAP'.
        """
        num_gap_points = self.__len__()
        # We append an extra duration (i.e., num_gap_points + 1)
        # This is because we need to insert the duration it takes
        # to get from the final gap point to the next collection window point
        # This duration is calculated alongside gaps so is inserted here for
        # the next collection window
        trajectory.durations[
            index_into_trajectory : index_into_trajectory + num_gap_points + 1
        ] = (np.array(self.duration) / TICK_S).astype(int)

        trajectory.user_programs[
            index_into_trajectory : index_into_trajectory + num_gap_points
        ] = UserProgram.GAP


class CollectionWindow:
    def __init__(
        self, start: int, end: int, slice: Slice, half_durations: npt.NDArray[float64]
    ):
        """Represents a collection window in a trajectory.

        :param start: Index into slice where this collection window starts
        :param end: Index into slice where this collection window ends
        :param slice: Information about a series of scan frames along a number of axes
        :param half_durations: Array of half the time required to get to a frame
        """
        self.start = start
        self.end = end
        self.slice = slice
        self.half_durations = half_durations

    def __len__(self):
        return ((self.end - self.start) * 2) + 1

    def insert_positions_and_velocities_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
        motor: Motor,
    ):
        """Inserts collection window positions and velocities into the trajectory.

        For all frames of the slice that fall within this window, this function will:
          - Insert an initial lower point to the trajectory
          - Insert a sequence of midpoint → upper → midpoint → ... → upper points
            until window ends
          - Calculate and insert a 2 point average velocity from the initial
            lower → midpoint (for the first velocity) and from the final
            midpoint → upper (for last velocity)
          - Calculate and insert 3 point average velocities from intermediate
            points, as these points have a previous and next point to use in the
            calculation
        """
        window_start_idx = index_into_trajectory
        window_end_idx = index_into_trajectory + self.__len__()

        # Lower bound at the segment start
        trajectory.positions[motor][window_start_idx] = self.slice.lower[motor][
            self.start
        ]

        # Fill mids into odd slots, uppers into even slots
        trajectory.positions[motor][window_start_idx + 1 : window_end_idx : 2] = (
            self.slice.midpoints[motor][self.start : self.end]
        )
        trajectory.positions[motor][window_start_idx + 2 : window_end_idx : 2] = (
            self.slice.upper[motor][self.start : self.end]
        )

        # For velocities we will need the relative distances
        mid_to_upper_velocities = (
            self.slice.upper[motor][self.start : self.end]
            - self.slice.midpoints[motor][self.start : self.end]
        ) / self.half_durations[self.start : self.end]
        lower_to_mid_velocities = (
            self.slice.midpoints[motor][self.start : self.end]
            - self.slice.lower[motor][self.start : self.end]
        ) / self.half_durations[self.start : self.end]

        # First velocity is the lower -> mid of first point
        trajectory.velocities[motor][window_start_idx] = lower_to_mid_velocities[0]

        # For the midpoints, we take the average of the
        # lower -> mid and mid -> upper velocities of the same point
        trajectory.velocities[motor][window_start_idx + 1 : window_end_idx : 2] = (
            lower_to_mid_velocities + mid_to_upper_velocities
        ) / 2

        # For the upper points, we need to take the average of the
        # mid -> upper velocity of the previous point and
        # lower -> mid velocity of the current point
        trajectory.velocities[motor][
            window_start_idx + 2 : (window_end_idx) - 1 : 2
        ] = (mid_to_upper_velocities[:-1] + lower_to_mid_velocities[1:]) / 2

        # For the last velocity take the mid to upper velocity
        trajectory.velocities[motor][window_end_idx - 1] = mid_to_upper_velocities[-1]

    def insert_durations_and_user_programs_into_trajectory(
        self,
        index_into_trajectory: int,
        trajectory: _Trajectory,
    ) -> None:
        """Inserts collection window durations and user programs into the trajectory.

        For all frames from the slice that fall within this window, this function will:
          - Insert a half duration for each midpoint and upper in the window,
            where a full duration is the duration of the corresponding slice frame
          - Insert user programs into the window as 'UserProgram.COLLECTION_WINDOW'

        Note: this function will not insert the first duration of the window,
        as this must be filled in by preceding ramp up duration or a gap segment
        """
        window_start_idx = index_into_trajectory
        window_end_idx = index_into_trajectory + self.__len__()

        trajectory.durations[window_start_idx + 1 : window_end_idx] = np.repeat(
            (self.half_durations[self.start : self.end] / TICK_S).astype(int),
            2,
        )

        trajectory.user_programs[window_start_idx:window_end_idx] = (
            UserProgram.COLLECTION_WINDOW
        )


@dataclass
class _Trajectory:
    positions: dict[Motor, np.ndarray]
    velocities: dict[Motor, np.ndarray]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    @classmethod
    def from_slice(
        cls, slice: Slice[Motor], ramp_up_time: float, motor_info: _PmacMotorInfo
    ) -> _Trajectory:
        """Parse a trajectory from a slice.

        :param slice: Information about a series of scan frames along a number of axes
        :param ramp_up_duration: Time required to ramp up to speed
        :param ramp_down: Booleon representing if we ramp down or not
        :returns Trajectory: Data class representing our parsed trajectory
        :raises RuntimeError: Slice must a duration array
        """
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")
        half_durations = slice_duration / 2

        scan_size = len(slice)
        # List of indices of the first frame of a collection window, after a gap
        collection_window_idxs: list[int] = np.where(slice.gap)[0].tolist()
        motors = slice.axes()

        # Precompute gaps
        # We structure our trajectory as a list of collection windows and gap segments
        segments: list[FillableSegment] = []
        total_gap_points = 0
        for collection_start_idx, collection_end_idx in zip(
            collection_window_idxs[:-1], collection_window_idxs[1:], strict=False
        ):
            # Add a collection window that we will fill later
            segments.append(
                CollectionWindow(
                    start=collection_start_idx,
                    end=collection_end_idx,
                    slice=slice,
                    half_durations=half_durations,
                )
            )

            # Now we precompute our gaps
            # Get entry velocities, exit velocities, and distances across gap
            entry_velocities, exit_velocities, distances = (
                _get_entry_and_exit_velocities(
                    motors, slice, half_durations, collection_end_idx
                )
            )

            # Get velocity and time profiles across gap
            time_arrays, velocity_arrays = _get_velocity_profile(
                motors, motor_info, entry_velocities, exit_velocities, distances
            )

            gap_segment = _calculate_profile_from_velocities(
                motors,
                slice,
                collection_end_idx,
                time_arrays,
                velocity_arrays,
            )

            # Add a gap segment
            segments.append(gap_segment)

            total_gap_points += len(gap_segment)

        # "collection_windows" does not include final window,
        # as no subsequeny gap to mark its termination
        # So, we add it here, ending it at the end of the slice
        segments.append(
            CollectionWindow(
                collection_window_idxs[-1], len(slice), slice, half_durations
            )
        )

        positions: dict[Motor, npt.NDArray[np.float64]] = {}
        velocities: dict[Motor, npt.NDArray[np.float64]] = {}

        # Initialise arrays
        # Trajectory size calculated from 2 points per frame (midpoint and upper)
        # Plus an initial lower point at the start of every collection window
        # Plus PVT points added between collection windows (gaps)
        trajectory_size = (
            2 * scan_size + len(collection_window_idxs)
        ) + total_gap_points
        positions = {motor: np.empty(trajectory_size, float) for motor in motors}
        velocities = {motor: np.empty(trajectory_size, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(trajectory_size, float)
        user_programs: npt.NDArray[np.int32] = np.empty(trajectory_size, int)
        # Ramp up time for start of collection window
        durations[0] = int(ramp_up_time / TICK_S)

        # Pass initialised arrays into a _Trajectory, that we fill later on
        trajectory = cls(
            positions=positions,
            velocities=velocities,
            durations=durations,
            user_programs=user_programs,
        )

        # Fill trajectory
        # Start by filling durations and user_programs once
        # as this is identical for all motors of a trajectory
        # Index keeps track of where we are in the trajectory
        index_into_trajectory = 0
        # Iterate over collection windows or gaps
        for segment in segments:
            # This inserts slice or gap durations and user_programs
            # into the output trajectory
            segment.insert_durations_and_user_programs_into_trajectory(
                index_into_trajectory=index_into_trajectory,
                trajectory=trajectory,
            )
            # The length of each segment moves the trajectory index
            index_into_trajectory += len(segment)
        # Now fill positions and velocities for each motor
        for motor in motors:
            # Reset index for positions and velocities, for each motor
            index_into_trajectory = 0
            for segment in segments:
                # This inserts slice or gap positions and velocites
                # into the output trajectory
                segment.insert_positions_and_velocities_into_trajectory(
                    index_into_trajectory=index_into_trajectory,
                    trajectory=trajectory,
                    motor=motor,
                )
                index_into_trajectory += len(segment)

            # Check that calculated velocities do not exceed motor's max velocity
            velocities_above_limit_mask = (
                np.abs(trajectory.velocities[motor])
                - motor_info.motor_max_velocity[motor]
            ) / motor_info.motor_max_velocity[motor] >= 1e-6
            if velocities_above_limit_mask.any():
                # Velocities above motor max velocity
                bad_velocities = trajectory.velocities[motor][
                    velocities_above_limit_mask
                ]
                # Indices in trajectory above motor max velocity
                # np.nonzero returns tuple, but as only one mask passed, we need index 0
                indices_to_bad_velocities = np.nonzero(velocities_above_limit_mask)[0]
                raise ValueError(
                    f"{motor.name} velocity exceeds motor's max velocity of "
                    f"{motor_info.motor_max_velocity[motor]} "
                    f"at trajectory indices {indices_to_bad_velocities.tolist()}: "
                    f"{bad_velocities}"
                )

        return trajectory

    def append_ramp_down(
        self,
        ramp_down_pos: dict[Motor, np.float64],
        ramp_down_time: float,
        ramp_down_velocity: float,
    ) -> _Trajectory:
        self.durations = np.append(self.durations, [int(ramp_down_time / TICK_S)])
        self.user_programs = np.append(self.user_programs, UserProgram.END)
        for motor in ramp_down_pos.keys():
            self.positions[motor] = np.append(
                self.positions[motor], [ramp_down_pos[motor]]
            )
            self.velocities[motor] = np.append(
                self.velocities[motor], [ramp_down_velocity]
            )

        return self


@dataclass
class _PmacMotorInfo:
    cs_port: str
    cs_number: int
    motor_cs_index: dict[Motor, int]
    motor_acceleration_rate: dict[Motor, float]
    motor_max_velocity: dict[Motor, float]

    @classmethod
    async def from_motors(cls, pmac: PmacIO, motors: Sequence[Motor]) -> _PmacMotorInfo:
        """Creates a _PmacMotorInfo instance based on a  controller and list of motors.

        :param pmac: The PMAC device
        :param motors: Sequence of motors involved in trajectory
        :raises RuntimeError:
            if motors do not share common CS port or CS number, or if
            motors do not have unique CS index assignments
        :returns:
            _PmacMotorInfo instance with motor's common CS port and CS number, and
            dictionaries of motor's to their unique CS index and accelerate rate

        """
        assignments = {
            motor: pmac.assignment[pmac.motor_assignment_index[motor]]
            for motor in motors
        }

        cs_ports, cs_numbers, cs_axes, velocities, accls = await asyncio.gather(
            gather_dict(
                {motor: assignments[motor].cs_port.get_value() for motor in motors}
            ),
            gather_dict(
                {motor: assignments[motor].cs_number.get_value() for motor in motors}
            ),
            gather_dict(
                {
                    motor: assignments[motor].cs_axis_letter.get_value()
                    for motor in motors
                }
            ),
            gather_dict({motor: motor.max_velocity.get_value() for motor in motors}),
            gather_dict(
                {motor: motor.acceleration_time.get_value() for motor in motors}
            ),
        )

        # check if the values in cs_port and cs_number are the same
        cs_ports = set(cs_ports.values())

        if len(cs_ports) != 1:
            raise RuntimeError(
                "Failed to fetch common CS port."
                "Motors passed are assigned to multiple CS ports:"
                f"{list(cs_ports)}"
            )

        cs_port = cs_ports.pop()

        cs_numbers = set(cs_numbers.values())
        if len(cs_numbers) != 1:
            raise RuntimeError(
                "Failed to fetch common CS number."
                "Motors passed are assigned to multiple CS numbers:"
                f"{list(cs_numbers)}"
            )

        cs_number = cs_numbers.pop()

        motor_cs_index = {}
        for motor in cs_axes:
            try:
                if not cs_axes[motor]:
                    raise ValueError
                motor_cs_index[motor] = CS_LETTERS.index(cs_axes[motor])
            except ValueError as err:
                raise ValueError(
                    "Failed to get motor CS index. "
                    f"Motor {motor.name} assigned to '{cs_axes[motor]}' "
                    f"but must be assignmed to '{CS_LETTERS}"
                ) from err
            if len(set(motor_cs_index.values())) != len(motor_cs_index.items()):
                raise RuntimeError(
                    "Failed to fetch distinct CS Axes."
                    "Motors passed are assigned to the same CS Axis"
                    f"{list(motor_cs_index)}"
                )

        motor_acceleration_rate = {
            motor: float(velocities[motor]) / float(accls[motor])
            for motor in velocities
        }

        return _PmacMotorInfo(
            cs_port, cs_number, motor_cs_index, motor_acceleration_rate, velocities
        )


def calculate_ramp_position_and_duration(
    slice: Slice[Motor], motor_info: _PmacMotorInfo, is_up: bool
) -> tuple[dict[Motor, np.float64], float]:
    """Calculate the the required ramp position and duration of a trajectory.

    This function will:
      - Calculate the ramp time required to achieve each motor's
        initial entry velocity into the first frame of a slice
        or final exit velocity out of the last frame of a slice
      - Use the longest ramp time to calculate all motor's
        ramp up positions.

    :param slice: Information about a series of scan frames along a number of axes
    :param motor_info: Instance of _PmacMotorInfo
    :param is_up: Boolean representing ramping up into a frame or down out of a frame
    :returns tuple: A tuple containing:
        dict: Motor to ramp positions
        float: Ramp time required for all motors
    """
    if slice.duration is None:
        raise ValueError("Slice must have a duration")

    scan_axes = slice.axes()
    idx = 0 if is_up else -1

    velocities: dict[Motor, float] = {}
    ramp_times: list[float] = []
    for axis in scan_axes:
        velocity = (slice.upper[axis][idx] - slice.lower[axis][idx]) / slice.duration[
            idx
        ]
        velocities[axis] = velocity
        ramp_times.append(abs(velocity) / motor_info.motor_acceleration_rate[axis])
    ramp_times.append(
        MIN_TURNAROUND
    )  # Adding a 2ms ramp time as a min tournaround time
    max_ramp_time = max(ramp_times)

    motor_to_ramp_position = {}
    sign = -1 if is_up else 1
    for axis, v in velocities.items():
        ref_pos = slice.lower[axis][0] if is_up else slice.upper[axis][-1]
        displacement = 0.5 * v * max_ramp_time
        motor_to_ramp_position[axis] = ref_pos + sign * displacement

    return (motor_to_ramp_position, max_ramp_time)


def _get_velocity_profile(
    motors: list[Motor],
    motor_info: _PmacMotorInfo,
    start_velocities: dict[Motor, np.float64],
    end_velocities: dict[Motor, np.float64],
    distances: dict[Motor, float],
) -> tuple[dict[Motor, npt.NDArray[np.float64]], dict[Motor, npt.NDArray[np.float64]]]:
    """Generate time and velocity profiles for motors across a gap.

    For each motor, a `VelocityProfile` is constructed.
    Profiles are iteratively recalculated to converge on a
    consistent minimum total gap time across all motors.

    This function will:
      - Initialise with a minimum turnaround time (`MIN_TURNAROUND`).
      - Build a velocity profile for each motor and determine the total
        move time required.
      - Update the minimum total gap time to the maximum of these totals.
      - Repeat until all profiles agree on the same minimum time or an
        iteration limit (i.e., 2) is reached.

    :param motors: Sequence of motors involved in trajectory
    :param motor_info: Instance of _PmacMotorInfo
    :param start_velocities: Motor velocities at start of gap
    :param end_velocities: Motor velocities at end of gap
    :param distances: Motor distances required to travel accross gap
    :raises ValueError: Cannot converge on common minimum time in 2 iterations
    :returns tuple: A tuple containing:
        dict: Motor's absolute timestamps of their velocity changes
        dict: Motor's velocity changes
    """
    profiles: dict[Motor, VelocityProfile] = {}
    time_arrays = {}
    velocity_arrays = {}

    min_time = MIN_TURNAROUND
    iterations = 2

    while iterations > 0:
        new_min_time = 0.0  # reset for this iteration

        for motor in motors:
            # Build profile for this motor
            p = VelocityProfile(
                start_velocities[motor],
                end_velocities[motor],
                distances[motor],
                min_time,
                motor_info.motor_acceleration_rate[motor],
                motor_info.motor_max_velocity[motor],
                0,
                MIN_INTERVAL,
            )
            p.get_profile()

            profiles[motor] = p
            new_min_time = max(new_min_time, p.t_total)

        # Check if all profiles have converged on min_time
        if np.isclose(new_min_time, min_time):
            for motor in motors:
                time_arrays[motor], velocity_arrays[motor] = profiles[
                    motor
                ].make_arrays()
            return time_arrays, velocity_arrays
        else:
            min_time = new_min_time
            iterations -= 1  # Get profiles with new minimum turnaround

    raise ValueError(
        "Failed to get a consistent time when calculating velocity profiles."
    )


def _get_entry_and_exit_velocities(
    motors: list[Motor],
    slice: Slice,
    half_durations: npt.NDArray[float64],
    gap: int,
) -> tuple[
    dict[Motor, np.float64],
    dict[Motor, np.float64],
    dict[Motor, float],
]:
    """Compute motor entry and exit velocities across a gap.

    For each motor, this function:
      - Calculates the midpoint velocity before and after the gap
      - Uses midpoint distances (lower → midpoint and midpoint → upper) to
        calculate the velocity just before entering the gap (entry velocity)
        and just after exiting the gap (exit velocity).
      - Computes the travel distance across the gap from the upper point of
        the preceding frame to the lower point of the following frame.

    :param motors: Sequence of motors involved in trajectory
    :param slice: Information about a series of scan frames along a number of axes
    :param half_durations: Array of half the time required to get to a frame
    :param gap: Index into the slice where gap has occured
    :returns tuple: A tuple containing:
        dict: Motor to entry velocity into gap
        dict: Motor to exit velocity out of gap
        dict: Motor to distance to travel across gap
    """
    entry_velocities: dict[Motor, np.float64] = {}
    exit_velocities: dict[Motor, np.float64] = {}
    distances: dict[Motor, float] = {}
    for motor in motors:
        #            x
        #        x       x
        #    x               x
        #    vl  vlm vm  vmu vu
        # Given distances from Frame, lower, midpoint, upper, calculate
        # vl for entry into gap (i.e., gap-1) and vu for exit out of gap
        entry_lower_upper_distance = (
            slice.upper[motor][gap - 1] - slice.lower[motor][gap - 1]
        )
        exit_lower_upper_distance = slice.upper[motor][gap] - slice.lower[motor][gap]

        entry_midpoint_velocity = entry_lower_upper_distance / (
            2 * half_durations[gap - 1]
        )
        exit_midpoint_velocity = exit_lower_upper_distance / (2 * half_durations[gap])

        # For entry, halfway point is vlm
        # so calculate lower to midpoint distance (i.e., dlm)
        lower_midpoint_distance = (
            slice.midpoints[motor][gap - 1] - slice.lower[motor][gap - 1]
        )
        # For exit, halfway point is vmu
        # so calculate midpoint to upper distance (i.e., dmu)
        midpoint_upper_distance = slice.upper[motor][gap] - slice.midpoints[motor][gap]

        # Extrapolate to get our entry or exit velocity
        # For example:
        # (vl + vm) / 2 = vlm
        # so vl = 2 * vlm - vm
        # where vlm = dlm / (t/2)
        # Therefore, velocity from point just before gap
        entry_velocities[motor] = (
            2 * (lower_midpoint_distance / half_durations[gap - 1])
            - entry_midpoint_velocity
        )

        # Velocity from point just after gap
        exit_velocities[motor] = (
            2 * (midpoint_upper_distance / half_durations[gap]) - exit_midpoint_velocity
        )

        # Travel distance across gap
        distances[motor] = slice.lower[motor][gap] - slice.upper[motor][gap - 1]
        if np.isclose(distances[motor], 0.0, atol=1e-12):
            distances[motor] = 0.0

    return entry_velocities, exit_velocities, distances


def _calculate_profile_from_velocities(
    motors: list[Motor],
    slice: Slice,
    gap: int,
    time_arrays: dict[Motor, npt.NDArray[np.float64]],
    velocity_arrays: dict[Motor, npt.NDArray[np.float64]],
) -> GapSegment:
    """Convert per-axis time/velocity profiles into aligned time/position profiles.

    Given per-axis arrays of times and corresponding velocities,
    this builds a single unified timeline containing all unique velocity change points
    from every axis. It then steps through that timeline, and for each axis:

    * If the current time matches one of the axis's own velocity change points,
        use that known velocity.
    * Otherwise, linearly interpolate between the axis's previous and next
        known velocities, based on how far through that section we are.

    At each unified time step, the velocity is integrated over the step duration
    (using the trapezoidal rule) to update the axis's position. This produces
    per-axis position and velocity arrays that are aligned to the same global
    time grid.

    Example:
        combined_times = [0.1, 0.2, 0.3, 0.4]
        axis_times[motor] = [0.1, 0.4]
        velocity_array[motor] = [2, 5]

        At 0.1 → known vel = 2 (use directly)
        At 0.2 → 1/3 of the way to next vel → 3.0
        At 0.3 → 2/3 of the way to next vel → 4.0
        At 0.4 → known vel = 5 (use directly)

        These instantaneous velocities are integrated over each Δt to yield
        positions aligned with the global timeline.

    :param motors: Sequence of motors involved in trajectory
    :param slice: Information about a series of scan frames along a number of axes
    :param gap: Index into slice where gap has occured
    :param time_arrays: Motor's absolute timestamps of velocity changes
    :param velocity_arrays: Motor's velocity changes
    :returns GapSegment: Class representing a segment of a trajectory that is a gap
    """
    # Combine all per-axis time points into a single sorted array of times
    # This way we can evaluate each motor along the same timeline
    # We know all axes positions at t=0, so we drop this point
    combined_times = np.sort(np.unique(np.concatenate(list(time_arrays.values()))))[1:]

    # We convert a list of t into a list of Δt
    # We do this by substracting against previous cumulative time
    time_intervals = np.diff(np.concatenate(([0.0], combined_times))).tolist()

    # We also know all axes positions when t=t_final, so we drop this point
    # However, we need the interval for the next collection window, so we store it
    *time_intervals, final_interval = time_intervals
    combined_times = combined_times[:-1]
    num_intervals = len(time_intervals)

    # Prepare dicts for the resulting position and velocity profiles over the gap
    positions: dict[Motor, npt.NDArray[np.float64]] = {}
    velocities: dict[Motor, npt.NDArray[np.float64]] = {}

    # Loop over each motor and integrate its velocity profile over the unified times
    for motor in motors:
        axis_times = time_arrays[motor]
        axis_velocities = velocity_arrays[motor]
        axis_position = slice.upper[motor][
            gap - 1
        ]  # start position at beginning of the gap
        prev_interval_vel = axis_velocities[
            0
        ]  # last velocity seen from the previous global time interval
        time_since_prev_axis_point = 0.0  # elapsed time since the last velocity point
        axis_idx = 1  # index into this axis's velocity/time arrays

        # Allocate output arrays for this motor with correct size
        positions[motor] = np.empty(num_intervals, dtype=np.float64)
        velocities[motor] = np.empty(num_intervals, dtype=np.float64)

        # Step through each interval in the Δt list
        for i, dt in enumerate(time_intervals):
            next_vel = axis_velocities[axis_idx]
            prev_vel = axis_velocities[axis_idx - 1]
            axis_dt = axis_times[axis_idx] - axis_times[axis_idx - 1]

            if np.isclose(combined_times[i], axis_times[axis_idx]):
                # If the current combined time exactly matches this motor's
                # next velocity change point, no interpolation is needed, so:
                this_vel = next_vel
                axis_idx += 1
                time_since_prev_axis_point = 0.0
            else:
                # Otherwise, linearly interpolate velocity between the previous
                # and next known velocity points for this motor
                time_since_prev_axis_point += dt
                # The fraction of the way we are from previous to next known velocities
                # for this motor
                frac = time_since_prev_axis_point / axis_dt
                # Interpolate for our velocity
                this_vel = prev_vel + frac * (next_vel - prev_vel)

            # Integrate velocity over this interval to update position.
            # Using the trapezoidal rule:
            delta_pos = 0.5 * (prev_interval_vel + this_vel) * dt
            axis_position += delta_pos
            prev_interval_vel = this_vel  # update for next loop

            # Store the computed position and velocity for this interval
            positions[motor][i] = axis_position
            velocities[motor][i] = this_vel

    return GapSegment(
        positions=positions,
        velocities=velocities,
        duration=time_intervals + [final_interval],
    )
