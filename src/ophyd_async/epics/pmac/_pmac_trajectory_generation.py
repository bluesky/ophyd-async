from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from functools import partial
from typing import TypeVar

import numpy as np
import numpy.typing as npt
from numpy import float64
from scanspec.core import Slice
from velocity_profile.velocityprofile import VelocityProfile

from ophyd_async.core import error_if_none
from ophyd_async.epics.motor import Motor

from ._pmac_trajectory import _PmacMotorInfo

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001
MIN_TURNAROUND = 0.002
MIN_INTERVAL = 0.002

IndexType = TypeVar("IndexType", int, slice, npt.NDArray[np.int_], list[int])


class UserProgram(IntEnum):
    COLLECTION_WINDOW = 1  # Period within a collection window
    GAP = 2  # Transition period between collection windows
    END = 8  # Post-scan state


@dataclass
class PVT:
    position: dict[Motor, float64]
    velocity: dict[Motor, float64]
    time: float64

    @classmethod
    def default(cls, motors: list[Motor]) -> PVT:
        return cls(
            position={motor: np.float64(0.0) for motor in motors},
            velocity={motor: np.float64(0.0) for motor in motors},
            time=np.float64(0.0),
        )


@dataclass
class _Trajectory:
    positions: dict[Motor, np.ndarray]
    velocities: dict[Motor, np.ndarray]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    def __len__(self) -> int:
        return len(self.user_programs)

    def __getitem__(self, idx: IndexType) -> _Trajectory:
        return _Trajectory(
            positions={m: arr[idx] for m, arr in self.positions.items()},
            velocities={m: arr[idx] for m, arr in self.velocities.items()},
            user_programs=self.user_programs[idx],
            durations=self.durations[idx],
        )

    def append_ramp_down(
        self,
        entry_pvt: PVT,
        ramp_down_pos: dict[Motor, np.float64],
        ramp_down_time: float,
        ramp_down_velocity: float,
    ) -> _Trajectory:
        self.durations = np.append(self.durations, [entry_pvt.time, ramp_down_time])
        self.user_programs = np.append(
            self.user_programs, [UserProgram.COLLECTION_WINDOW, UserProgram.END]
        )
        for motor in ramp_down_pos.keys():
            self.positions[motor] = np.append(
                self.positions[motor], [entry_pvt.position[motor], ramp_down_pos[motor]]
            )
            self.velocities[motor] = np.append(
                self.velocities[motor], [entry_pvt.velocity[motor], ramp_down_velocity]
            )

        return self

    @classmethod
    def from_slice(
        cls,
        slice: Slice[Motor],
        motor_info: _PmacMotorInfo,
        entry_pvt: PVT,
        ramp_up_time: float | None = None,
    ) -> tuple[_Trajectory, PVT]:
        # List of indices into slice where gaps occur
        gap_indices: list[int] = np.where(slice.gap)[0].tolist()
        motors = slice.axes()

        # Given a ramp up time is provided, we must be at a
        # gap in the trajectory, that we can ramp up through
        if gap_indices[0] != 0 and ramp_up_time:
            raise RuntimeError(
                "Slice does not start with a gap, if ramp up time provided. "
                f"Ramp up time given: {ramp_up_time}."
            )

        # Find change points in the slice
        # For example, if we have [True, False, False, False, False, True, False],
        # there are changes between indices 0-1, 4-5, and 5-6, so our change points
        # become [1, 5, 6]
        change_points = np.flatnonzero(slice.gap[1:] != slice.gap[:-1]) + 1
        # We must always handle the entire slice we are given, so we ensure
        # index 0 and len(slice) are included
        boundaries = np.r_[0, change_points, len(slice)]
        # At this point, we have boundaries of slice segments
        # Using our previous example, we get [0, 1, 5, 6, 7]
        # which tells us our segments are at 0-1, 1-5, 5-6, and 6-7

        # For each segment of our slice (i.e., a collection window or a gap),
        # we get a single boolean representing if the segment is a gap or not
        # We only need to look at the start of our segments to determine
        # if they are gaps or not (i.e., boundaries[:-1])
        # Using our previous example, we find that:
        #   0-1: gap
        #   1-5: collection window
        #   5-6: gap
        #   6-7: collection window
        is_gap_segment = slice.gap[boundaries[:-1]]

        # Indexing into segments that are not gaps
        # we extract the collection window start and end indices
        collection_window_starts = boundaries[:-1][~is_gap_segment]
        collection_window_ends = boundaries[1:][~is_gap_segment]
        # `starts` and `ends` are taken from the same mask (i.e., ~is_segment_gap),
        # so they always have the same length.
        # Every segment is either a gap or a collection window,
        # so len(starts) + len(gap_indices) == len(is_segment_gap).

        gap_iter = iter(gap_indices)
        collection_window_iter = iter(
            zip(collection_window_starts, collection_window_ends, strict=False)
        )

        sub_traj_funcs = []
        # Given a segment is either a gap or a collection window
        # we can iterate over each segment and advance the
        # gap OR collection window iterator safely.
        if ramp_up_time:
            gap_index = next(gap_iter)
            sub_traj_funcs.append(
                partial(
                    _Trajectory.from_gap,
                    motor_info,
                    gap_index,
                    motors,
                    slice,
                    ramp_up_time=ramp_up_time,
                )
            )
            is_gap_segment = is_gap_segment[1:]
        for is_gap in is_gap_segment:
            if is_gap:
                gap_index = next(gap_iter)
                sub_traj_funcs.append(
                    partial(
                        _Trajectory.from_gap,
                        motor_info,
                        gap_index,
                        motors,
                        slice,
                    )
                )
            else:
                start, end = next(collection_window_iter)
                sub_traj_funcs.append(
                    partial(
                        _Trajectory.from_collection_window,
                        start,
                        end,
                        motors,
                        slice,
                    )
                )

        sub_trajectories: list[_Trajectory] = []
        # If no sub trajectories, initial frame is the end frame
        exit_pvt = entry_pvt
        for func in sub_traj_funcs:
            # Build each sub trajectory, passing the last PVT
            # to the next sub trajectory to build upon
            # Explicitly defining initial and end PVTs
            # to clearly show that the last PVT of a trajectory
            # is passed as the first PVT of the next trajectory
            traj, exit_pvt = func(entry_pvt)
            entry_pvt = exit_pvt
            sub_trajectories.append(traj)

        # If we are ramping up, we are already starting at the
        # ramp up position, so remove this point from the
        # trajectory
        if ramp_up_time:
            sub_trajectories[0] = sub_trajectories[0][1:]

        # Combine sub trajectories
        total_trajectory = _Trajectory.from_trajectories(sub_trajectories, motors)

        return total_trajectory, exit_pvt

    @classmethod
    def from_trajectories(
        cls, sub_trajectories: list[_Trajectory], motors: list[Motor]
    ) -> _Trajectory:
        # Initialise arrays to insert sub arrays into
        total_points = sum(len(trajectory) for trajectory in sub_trajectories)
        positions = {motor: np.empty(total_points, float) for motor in motors}
        velocities = {motor: np.empty(total_points, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(total_points, float)
        user_programs: npt.NDArray[np.int32] = np.empty(total_points, int)

        # Keep track of where we are in overall trajectory
        index_into_trajectory = 0
        for trajectory in sub_trajectories:
            # Insert sub trajectory arrays into overall trajectory arrays
            durations[
                index_into_trajectory : index_into_trajectory + len(trajectory)
            ] = trajectory.durations
            user_programs[
                index_into_trajectory : index_into_trajectory + len(trajectory)
            ] = trajectory.user_programs
            for motor in motors:
                positions[motor][
                    index_into_trajectory : index_into_trajectory + len(trajectory)
                ] = trajectory.positions[motor]
                velocities[motor][
                    index_into_trajectory : index_into_trajectory + len(trajectory)
                ] = trajectory.velocities[motor]
            # Update where we are in the overall trajectory
            index_into_trajectory += len(trajectory)

        trajectory = _Trajectory(
            positions=positions,
            velocities=velocities,
            durations=durations,
            user_programs=user_programs,
        )

        return trajectory

    @classmethod
    def from_collection_window(
        cls,
        start: int,
        end: int,
        motors: list[Motor],
        slice: Slice,
        entry_pvt: PVT,
    ) -> tuple[_Trajectory, PVT]:
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")
        half_durations = slice_duration / 2
        if end > len(half_durations):
            # Clamp collection window if no more frames
            end = len(half_durations)
        trajectory_size = 2 * len(half_durations[start:end])
        positions = {motor: np.empty(trajectory_size, float) for motor in motors}
        velocities = {motor: np.empty(trajectory_size, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(trajectory_size, float)
        user_programs: npt.NDArray[np.int32] = np.empty(trajectory_size, int)

        # Initialise exit PVT
        exit_pvt = PVT.default(motors)

        for motor in motors:
            positions[motor][::2] = slice.lower[motor][start:end]
            positions[motor][1::2] = slice.midpoints[motor][start:end]

            # For velocities we will need the relative distances
            mid_to_upper_velocities, lower_to_mid_velocities = get_half_velocities(
                motor, slice, half_durations, start, end
            )

            # Smooth first lower point velocity with previous PVT
            velocities[motor][0] = (
                lower_to_mid_velocities[0] + entry_pvt.velocity[motor]
            ) / 2

            # For the midpoints, we take the average of the
            # lower -> mid and mid -> upper velocities of the same point
            velocities[motor][1::2] = (
                lower_to_mid_velocities + mid_to_upper_velocities
            ) / 2

            # For the upper points, we need to take the average of the
            # mid -> upper velocity of the previous point and
            # lower -> mid velocity of the current point
            velocities[motor][2::2] = (
                mid_to_upper_velocities[:-1] + lower_to_mid_velocities[1:]
            ) / 2

            exit_pvt.position[motor] = slice.upper[motor][end - 1]
            exit_pvt.velocity[motor] = mid_to_upper_velocities[-1]

        durations[0] = entry_pvt.time
        durations[1:] = np.repeat(
            (half_durations[start:end]),
            2,
        )[1:]

        user_programs = np.repeat(UserProgram.COLLECTION_WINDOW, len(user_programs))

        exit_pvt.time = half_durations[end - 1]

        trajectory = _Trajectory(
            positions=positions,
            velocities=velocities,
            durations=durations,
            user_programs=user_programs,
        )

        return trajectory, exit_pvt

    @classmethod
    def from_gap(
        cls,
        motor_info: _PmacMotorInfo,
        gap: int,
        motors: list[Motor],
        slice: Slice,
        entry_pvt: PVT,
        ramp_up_time: float | None = None,
    ) -> tuple[_Trajectory, PVT]:
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")
        half_durations = slice_duration / 2

        entry_velocities = entry_pvt.velocity
        exit_velocities = {
            motor: (slice.midpoints[motor][gap] - slice.lower[motor][gap])
            / half_durations[gap]
            for motor in motors
        }
        distances = {
            motor: 0.0
            if np.isclose(
                (distance := slice.lower[motor][gap] - entry_pvt.position[motor]),
                0.0,
                atol=1e-12,
            )
            else distance
            for motor in motors
        }

        # Get velocity and time profiles across gap
        time_arrays, velocity_arrays = _get_velocity_profile(
            motors,
            motor_info,
            entry_velocities,
            exit_velocities,
            distances,
            ramp_up_time,
        )

        gap_positions, gap_velocities, gap_durations = (
            _calculate_profile_from_velocities(
                motors,
                entry_pvt,
                time_arrays,
                velocity_arrays,
            )
        )

        positions = {
            motor: np.empty(len(gap_durations) + 2, dtype=np.float64)
            for motor in motors
        }
        velocities = {
            motor: np.empty(len(gap_durations) + 2, dtype=np.float64)
            for motor in motors
        }
        durations = np.empty(len(gap_durations) + 2, dtype=np.float64)

        # Initialise exit PVT
        exit_pvt = PVT.default(motors)

        for motor in motors:
            # Insert last collection windows upper point
            positions[motor][0] = entry_pvt.position[motor]
            velocities[motor][0] = entry_pvt.velocity[motor]
            durations[0] = entry_pvt.time

            # Insert gap information
            positions[motor][1:-2] = gap_positions[motor]
            velocities[motor][1:-2] = gap_velocities[motor]
            durations[1:-1] = gap_durations

            # Insert first 2 points of next collection window
            positions[motor][-2] = slice.lower[motor][gap]
            positions[motor][-1] = slice.midpoints[motor][gap]

            mid_to_upper_velocity, lower_to_mid_velocity = get_half_velocities(
                motor, slice, half_durations, gap, gap + 1
            )
            velocities[motor][-2] = lower_to_mid_velocity[0]

            velocities[motor][-1] = (
                lower_to_mid_velocity[0] + mid_to_upper_velocity[0]
            ) / 2
            durations[-1] = half_durations[gap]

            exit_pvt.position[motor] = slice.upper[motor][gap]
            exit_pvt.velocity[motor] = mid_to_upper_velocity[0]

        exit_pvt.time = half_durations[gap]

        trajectory = _Trajectory(
            positions=positions,
            velocities=velocities,
            durations=durations,
            user_programs=np.array(
                [1] + [2] * (len(gap_durations) - 1) + [1, 1], dtype=int
            ),
        )

        return trajectory, exit_pvt


def _get_velocity_profile(
    motors: list[Motor],
    motor_info: _PmacMotorInfo,
    start_velocities: dict[Motor, np.float64],
    end_velocities: dict[Motor, np.float64],
    distances: dict[Motor, float],
    ramp_up_time: float | None = None,
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

    min_time = ramp_up_time or MIN_TURNAROUND
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


def _calculate_profile_from_velocities(
    motors: list[Motor],
    entry_pvt: PVT,
    time_arrays: dict[Motor, npt.NDArray[np.float64]],
    velocity_arrays: dict[Motor, npt.NDArray[np.float64]],
) -> tuple[
    dict[Motor, npt.NDArray[np.float64]],
    dict[Motor, npt.NDArray[np.float64]],
    list[float],
]:
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
        axis_position = entry_pvt.position[
            motor
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

    return (
        positions,
        velocities,
        time_intervals + [final_interval],
    )


def get_half_velocities(
    motor: Motor,
    slice: Slice,
    half_durations: npt.NDArray[float64],
    start: int,
    end: int,
) -> tuple[npt.NDArray[float64], npt.NDArray[float64]]:
    mid_to_upper_velocities = (
        slice.upper[motor][start:end] - slice.midpoints[motor][start:end]
    ) / half_durations[start:end]
    lower_to_mid_velocities = (
        slice.midpoints[motor][start:end] - slice.lower[motor][start:end]
    ) / half_durations[start:end]

    return mid_to_upper_velocities, lower_to_mid_velocities
