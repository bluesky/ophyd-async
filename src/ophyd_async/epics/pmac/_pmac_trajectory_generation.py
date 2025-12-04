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
from ophyd_async.epics.pmac._utils import _PmacMotorInfo

MIN_TURNAROUND = 0.002
MIN_INTERVAL = 0.002

IndexType = TypeVar("IndexType", int, slice, npt.NDArray[np.int_], list[int])


class UserProgram(IntEnum):
    COLLECTION_WINDOW = 1  # Period within a collection window
    GAP = 2  # Transition period between collection windows
    END = 8  # Post-scan state


@dataclass
class PVT:
    """Represents a single position, velocity, and time point for multiple motors."""

    position: dict[Motor, float64]
    velocity: dict[Motor, float64]
    time: float64

    @classmethod
    def default(cls, motors: list[Motor]) -> PVT:
        """Initialise a PVT with zeros.

        :param motors: List of motors
        :returns: PVT instance with zero value placeholders
        """
        return cls(
            position={motor: np.float64(0.0) for motor in motors},
            velocity={motor: np.float64(0.0) for motor in motors},
            time=np.float64(0.0),
        )


@dataclass
class Trajectory:
    positions: dict[Motor, npt.NDArray[np.float64]]
    velocities: dict[Motor, npt.NDArray[np.float64]]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    def __len__(self) -> int:
        return len(self.user_programs)

    def with_ramp_down(
        self,
        entry_pvt: PVT,
        ramp_down_pos: dict[Motor, np.float64],
        ramp_down_time: float,
        ramp_down_velocity: float,
    ) -> Trajectory:
        # Make room for additional two points to ramp down
        # from a collection window upper to ramp down position
        trajectory_length = len(self.user_programs)
        total_length = trajectory_length + 2
        motors = ramp_down_pos.keys()

        positions = {motor: np.empty(total_length, float) for motor in motors}
        velocities = {motor: np.empty(total_length, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(total_length, float)
        user_programs: npt.NDArray[np.int32] = np.empty(total_length, int)

        durations[:trajectory_length] = self.durations
        durations[trajectory_length:] = [entry_pvt.time, ramp_down_time]

        user_programs[:trajectory_length] = self.user_programs
        user_programs[trajectory_length:] = [
            UserProgram.COLLECTION_WINDOW,
            UserProgram.END,
        ]

        for motor in ramp_down_pos.keys():
            positions[motor][:trajectory_length] = self.positions[motor]
            positions[motor][trajectory_length:] = [
                entry_pvt.position[motor],
                ramp_down_pos[motor],
            ]
            velocities[motor][:trajectory_length] = self.velocities[motor]
            velocities[motor][trajectory_length:] = [
                entry_pvt.velocity[motor],
                ramp_down_velocity,
            ]

        return Trajectory(
            positions=positions,
            velocities=velocities,
            user_programs=user_programs,
            durations=durations,
        )

    @classmethod
    def from_slice(
        cls,
        slice: Slice[Motor],
        motor_info: _PmacMotorInfo,
        entry_pvt: PVT | None = None,
        ramp_up_time: float | None = None,
    ) -> tuple[Trajectory, PVT]:
        """Parse a trajectory from a slice.

        :param slice: Information about a series of scan frames along a number of axes
        :param motor_info: Instance of _PmacMotorInfo
        :param entry_pvt: PVT entering this trajectory
        :param ramp_up_time: Time required to ramp up to speed
        :returns Trajectory: Data class representing our parsed trajectory
        """
        # List of indices into slice where gaps occur
        gap_indices: list[int] = np.where(slice.gap)[0].tolist()
        motors = slice.axes()

        # Given a ramp up time is provided, we must be at a
        # gap in the trajectory, that we can ramp up through
        if (not gap_indices or gap_indices[0] != 0) and ramp_up_time:
            raise RuntimeError(
                "Slice must start with a gap, if ramp up time provided. "
                f"Ramp up time given: {ramp_up_time}."
            )

        # Given a ramp up time is provided, we need to construct the PVT
        if (ramp_up_time is None) == (entry_pvt is None):
            raise RuntimeError(
                "Exactly one of ramp_up_time or entry_pvt must be provided."
                f"Provided ramp up time: {ramp_up_time} and entry PVT: {entry_pvt}"
            )

        # Find start and end indices for collection windows
        collection_windows = np.argwhere(
            np.diff(~(slice.gap), prepend=False, append=False)
        ).reshape((-1, 2))

        collection_window_iter = iter(collection_windows)
        sub_traj_funcs = []

        # Given we start at a collection window, insert it
        if not gap_indices or gap_indices[0] != 0:
            start, end = next(collection_window_iter)
            sub_traj_funcs.append(
                partial(
                    Trajectory.from_collection_window,
                    start,
                    end,
                    motors,
                    slice,
                )
            )

        # For each gap, insert a gap, followed by a collection window
        # given the distance to the next gap is greater than 1
        for gap in gap_indices:
            kwargs = {}
            if gap == 0 and ramp_up_time:
                kwargs["ramp_up_time"] = ramp_up_time
            sub_traj_funcs.append(
                partial(
                    Trajectory.from_gap,
                    motor_info,
                    gap,
                    motors,
                    slice,
                    **kwargs,
                )
            )
            if gap != len(slice.gap) - 1 and not slice.gap[gap + 1]:
                start, end = next(collection_window_iter)
                sub_traj_funcs.append(
                    partial(
                        Trajectory.from_collection_window,
                        start,
                        end,
                        motors,
                        slice,
                    )
                )

        sub_trajectories: list[Trajectory] = []
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

        # Combine sub trajectories
        total_trajectory = Trajectory.from_trajectories(sub_trajectories, motors)

        return total_trajectory, (exit_pvt or PVT.default(motors))

    @classmethod
    def from_trajectories(
        cls, sub_trajectories: list[Trajectory], motors: list[Motor]
    ) -> Trajectory:
        """Parse a trajectory from smaller strajectories.

        :param sub_trajectories: List of trajectories to concatenate
        :returns: Trajectory instance as concatenation of all sub trajectories
        """
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

        trajectory = Trajectory(
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
    ) -> tuple[Trajectory, PVT]:
        """Parse a trajectory from a collection window.

        For all frames of the slice that fall within this window, this function will:
          - Insert a sequence of lower → midpoint → lower → ... → midpoint points
            until window ends
          - Calculate and insert 3 point average velocities for these points, using the
            entry PVT to blend with previous trajectories

        :param start: Index into slice where collection window starts
        :param end: Index into slice where collection window end
        :param motors: List of motors involved in trajectory
        :param slice: Information about a series of scan frames along a number of axes
        :param entry_pvt: PVT entering this trajectory
        :returns: Tuple of:
            Trajectory instance encompassing collection window points
            PVT at exit of collection window
        """
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
            # Insert lower -> mid -> lower -> mid... positions
            positions[motor][::2] = slice.lower[motor][start:end]
            positions[motor][1::2] = slice.midpoints[motor][start:end]

            # For velocities we will need the relative distances
            mid_to_upper_velocities = (
                slice.upper[motor][start:end] - slice.midpoints[motor][start:end]
            ) / half_durations[start:end]
            lower_to_mid_velocities = (
                slice.midpoints[motor][start:end] - slice.lower[motor][start:end]
            ) / half_durations[start:end]

            # Smooth first lower point velocity with previous PVT
            velocities[motor][0] = (
                lower_to_mid_velocities[0] + entry_pvt.velocity[motor]
            ) / 2

            # For the midpoints, we take the average of the
            # lower -> mid and mid -> upper velocities of the same point
            velocities[motor][1::2] = (
                lower_to_mid_velocities + mid_to_upper_velocities
            ) / 2

            # For the lower points, we need to take the average of the
            # mid -> upper velocity of the previous point and
            # lower -> mid velocity of the current point
            velocities[motor][2::2] = (
                mid_to_upper_velocities[:-1] + lower_to_mid_velocities[1:]
            ) / 2

            # Exit PVT is the final upper point and its mid to upper velocity
            exit_pvt.position[motor] = slice.upper[motor][end - 1]
            exit_pvt.velocity[motor] = mid_to_upper_velocities[-1]

        durations = np.repeat(
            (half_durations[start:end]),
            2,
        )

        user_programs = np.repeat(UserProgram.COLLECTION_WINDOW, len(user_programs))

        exit_pvt.time = half_durations[end - 1]

        trajectory = Trajectory(
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
    ) -> tuple[Trajectory, PVT]:
        """Parse a trajectory from a gap.

        This function will:
          - Compute gap PVT points to bridge a previous and next collection window
          - Insert the previous collecion windows upper point into the trajectory
          - Insert the next collection windows first lower and midpoint
          - Calculate a 2 point average velocity for the first lower and midpoint
          - Produce an exit PVT of the next frames upper, midpoint-upper velocity, and
            time

        :param motor_info: Instance of _PmacMotorInfo
        :param gap: Index into slice where gap must occur
        :param motors: List of motors involved in trajectory
        :param slice: Information about a series of scan frames along a number of axes
        :param entry_pvt: PVT entering this trajectory
        :returns: Tuple of:
            Trajectory instance bridging previous and next collection windows with gap
            PVT at the start of the next collection window
        """
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")
        half_durations = slice_duration / 2

        # Initialise exit PVT
        exit_pvt = PVT.default(motors)

        # Fill arrays for gap exit (start of next collection window)
        end_positions = {motor: np.empty(2, dtype=np.float64) for motor in motors}
        end_velocities = {motor: np.empty(2, dtype=np.float64) for motor in motors}
        end_durations = np.empty(2, dtype=np.float64)
        for motor in motors:
            end_positions[motor][0] = slice.lower[motor][gap]
            end_positions[motor][1] = slice.midpoints[motor][gap]

            mid_to_upper_velocity = (
                slice.upper[motor][gap] - slice.midpoints[motor][gap]
            ) / half_durations[gap]
            lower_to_mid_velocity = (
                slice.midpoints[motor][gap] - slice.lower[motor][gap]
            ) / half_durations[gap]

            end_velocities[motor][0] = lower_to_mid_velocity

            end_velocities[motor][1] = (
                lower_to_mid_velocity + mid_to_upper_velocity
            ) / 2
            end_durations[1] = half_durations[gap]

            exit_pvt.position[motor] = slice.upper[motor][gap]
            exit_pvt.velocity[motor] = mid_to_upper_velocity

        exit_pvt.time = half_durations[gap]

        # If we are ramping up, don't compute gap PVTs
        if ramp_up_time:
            end_durations[0] = ramp_up_time
            return Trajectory(
                positions=end_positions,
                velocities=end_velocities,
                durations=end_durations,
                user_programs=np.array([1, 1], dtype=int),
            ), exit_pvt

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
        )

        # Calculate gap PVTs
        gap_positions, gap_velocities, gap_durations = (
            _calculate_profile_from_velocities(
                motors,
                entry_pvt,
                time_arrays,
                velocity_arrays,
            )
        )

        # Initialise larger arrays for last collection windows
        # final upper point, the gap points, and the next collection windows
        # initial lower and midpoints
        # gap_duration includes duration for next collection windows initial
        # lower point, so array_size = len(gap_duration) + 2
        positions = {
            motor: np.empty(len(gap_durations) + 2, dtype=np.float64)
            for motor in motors
        }
        velocities = {
            motor: np.empty(len(gap_durations) + 2, dtype=np.float64)
            for motor in motors
        }
        durations = np.empty(len(gap_durations) + 2, dtype=np.float64)

        for motor in motors:
            # Insert last collection windows upper point
            positions[motor][0] = entry_pvt.position[motor]
            velocities[motor][0] = entry_pvt.velocity[motor]
            durations[0] = entry_pvt.time

            # Insert gap information
            positions[motor][1:-2] = gap_positions[motor]
            velocities[motor][1:-2] = gap_velocities[motor]
            durations[1:-1] = gap_durations

            # Append first 2 points of next collection window
            positions[motor][-2:] = end_positions[motor]
            velocities[motor][-2:] = end_velocities[motor]
            durations[-1] = end_durations[-1]

        trajectory = Trajectory(
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
                # MIN_INTERVAL should be less than our convergence tolerance
                # such that motors snap to the same point in the time grid
                profiles[motor].quantize()
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
