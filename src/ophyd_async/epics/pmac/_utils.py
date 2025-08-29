from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
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


class FillableWindow(Protocol):
    def insert_points_into_trajectory(
        self,
        index_into_trajectory: int,
        positions: dict[Motor, npt.NDArray[np.float64]],
        velocities: dict[Motor, npt.NDArray[np.float64]],
        durations: npt.NDArray[float64],
        user_programs: npt.NDArray[np.int32],
        motor: Motor,
    ) -> int: ...


class GapSegment:
    def __init__(
        self,
        positions: dict[Motor, np.ndarray],
        velocities: dict[Motor, np.ndarray],
        duration: list[float],
        gap_length: int,
    ):
        self.positions = positions
        self.velocities = velocities
        self.duration = duration
        self.gap_length = gap_length

    def insert_points_into_trajectory(
        self,
        index_into_trajectory: int,
        positions: dict[Motor, npt.NDArray[np.float64]],
        velocities: dict[Motor, npt.NDArray[np.float64]],
        durations: npt.NDArray[float64],
        user_programs: npt.NDArray[np.int32],
        motor: Motor,
    ):
        num_gap_points = self.gap_length
        # Update how many gap points we've added so far
        # Insert gap points into end of collection window
        positions[motor][
            index_into_trajectory + 1 : index_into_trajectory + 1 + num_gap_points
        ] = self.positions[motor]
        velocities[motor][
            index_into_trajectory + 1 : index_into_trajectory + 1 + num_gap_points
        ] = self.velocities[motor]
        durations[
            index_into_trajectory + 1 : index_into_trajectory + 1 + num_gap_points
        ] = (np.array(self.duration) / TICK_S).astype(int)

        user_programs[
            index_into_trajectory + 1 : index_into_trajectory + num_gap_points
        ] = 2

        # Move index to end of gap segment
        index_into_trajectory += num_gap_points

        return index_into_trajectory


class CollectionWindow:
    def __init__(
        self, start: int, end: int, slice: Slice, half_durations: npt.NDArray[float64]
    ):
        self.start = start
        self.end = end
        self.slice = slice
        self.half_durations = half_durations

    def insert_points_into_trajectory(
        self,
        index_into_trajectory: int,
        positions: dict[Motor, npt.NDArray[np.float64]],
        velocities: dict[Motor, npt.NDArray[np.float64]],
        durations: npt.NDArray[float64],
        user_programs: npt.NDArray[np.int32],
        motor: Motor,
    ):
        window_length = self.end - self.start
        start_traj = index_into_trajectory
        end_traj = index_into_trajectory + (window_length * 2)

        # Move index to end of this collection window
        index_into_trajectory = end_traj

        # Lower bound at the segment start
        positions[motor][start_traj] = self.slice.lower[motor][self.start]

        # Fill mids into odd slots, uppers into even slots
        positions[motor][start_traj + 1 : (end_traj) + 1 : 2] = self.slice.midpoints[
            motor
        ][self.start : self.end]
        positions[motor][start_traj + 2 : (end_traj) + 1 : 2] = self.slice.upper[motor][
            self.start : self.end
        ]

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
        velocities[motor][start_traj] = lower_to_mid_velocities[0]

        # For the midpoints, we take the average of the
        # lower -> mid and mid-> upper velocities of the same point
        velocities[motor][start_traj + 1 : (end_traj) + 1 : 2] = (
            lower_to_mid_velocities + mid_to_upper_velocities
        ) / 2

        # For the upper points, we need to take the average of the
        # mid -> upper velocity of the previous point and
        # lower -> mid velocity of the current point
        velocities[motor][start_traj + 2 : (end_traj) : 2] = (
            mid_to_upper_velocities[:-1] + lower_to_mid_velocities[1:]
        ) / 2

        # For the last velocity take the mid to upper velocity
        velocities[motor][end_traj] = mid_to_upper_velocities[-1]

        durations[start_traj + 1 : end_traj + 1] = np.repeat(
            (self.half_durations[self.start : self.end] / TICK_S).astype(int),
            2,
        )

        user_programs[start_traj : end_traj + 1] = 1

        return index_into_trajectory


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
        """Parse a trajectory with no gaps from a slice.

        :param slice: Information about a series of scan frames along a number of axes
        :param ramp_up_duration: Time required to ramp up to speed
        :param ramp_down: Booleon representing if we ramp down or not
        :returns Trajectory: Data class representing our parsed trajectory
        :raises RuntimeError: Slice must have no gaps and a duration array
        """
        slice_duration = error_if_none(slice.duration, "Slice must have a duration")
        half_durations = slice_duration / 2

        scan_size = len(slice)
        # List of indices of the first frame of a collection window, after a gap
        collection_windows: list[int] = np.where(slice.gap)[0].tolist()
        motors = slice.axes()

        # Precompute gaps
        # We structure our trajectory as a list of collection windows and gap segments
        segments: list[FillableWindow] = []
        total_gap_points = 0
        for collection_start, collection_end in zip(
            collection_windows[:-1], collection_windows[1:], strict=False
        ):
            # Add a collection window that we will fill later
            segments.append(
                CollectionWindow(
                    start=collection_start,
                    end=collection_end,
                    slice=slice,
                    half_durations=half_durations,
                )
            )

            # Now we precompute our gaps
            # Get entry velocities, exit velocities, and distances across gap
            entry_velocities, exit_velocities, distances = (
                _get_entry_and_exit_velocities(
                    motors, slice, half_durations, collection_end
                )
            )

            # Get velocity and time profiles across gap
            time_arrays, velocity_arrays = _get_velocity_profile(
                motors, motor_info, entry_velocities, exit_velocities, distances
            )

            start_positions: dict[Motor, npt.NDArray[float64]] = {
                motor: slice.upper[motor][collection_end - 1] for motor in motors
            }

            gap_segment = _calculate_profile_from_velocities(
                motors, time_arrays, velocity_arrays, start_positions
            )

            # Add a gap segment
            segments.append(gap_segment)

            total_gap_points += gap_segment.gap_length

        # "collection_windows" does not include final window,
        # as no subsequeny gap to mark its termination
        # So, we add it here, ending it at the end of the slice
        segments.append(
            CollectionWindow(collection_windows[-1], len(slice), slice, half_durations)
        )

        positions: dict[Motor, npt.NDArray[np.float64]] = {}
        velocities: dict[Motor, npt.NDArray[np.float64]] = {}

        # Initialise arrays
        # Trajectory size calculated from 2 points per frame (midpoint and upper)
        # Plus an initial lower point
        # Plus PVT points added between collection windows (gaps)
        trajectory_size = ((2 * scan_size) + 1) + total_gap_points
        positions = {motor: np.empty(trajectory_size, float) for motor in motors}
        velocities = {motor: np.empty(trajectory_size, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(trajectory_size, float)
        # Default to program 1 to assume we acquire at all points
        user_programs: npt.NDArray[np.int32] = np.empty(trajectory_size, float)

        # Ramp up time for start of collection window
        durations[0] = int(ramp_up_time / TICK_S)

        # Fill trajectory
        for motor in motors:
            # Keeps track of where we are in the trajectory
            index_into_trajectory = 0
            # Iterate over collection windows or gaps
            for segment in segments:
                # This inserts slice points or gap points into the output arrays
                # Returns a new index into our trajectory arrays
                # where more points can be inserted
                index_into_trajectory = segment.insert_points_into_trajectory(
                    index_into_trajectory=index_into_trajectory,
                    positions=positions,
                    velocities=velocities,
                    durations=durations,
                    user_programs=user_programs,
                    motor=motor,
                )

            # Check that calculated velocities do not exceed motor's max velocity
            velocities_above_limit = (
                np.abs(velocities[motor]) - motor_info.motor_max_velocity[motor]
            ) / motor_info.motor_max_velocity[motor] >= 1e-6
            if velocities_above_limit.any():
                # Velocities above motor max velocity
                bad_vals = velocities[motor][velocities_above_limit]
                # Indices in trajectory above motor max velocity
                bad_indices = np.nonzero(velocities_above_limit)[0]
                raise ValueError(
                    f"{motor.name} velocity exceeds motor's max velocity of "
                    f"{motor_info.motor_max_velocity[motor]} "
                    f"at trajectory indices {bad_indices.tolist()}: {bad_vals}"
                )

        return cls(
            positions=positions,
            velocities=velocities,
            user_programs=user_programs,
            durations=durations,
        )

    def append_ramp_down(
        self,
        ramp_down_pos: dict[Motor, np.float64],
        ramp_down_time: float,
        ramp_down_velocity: float,
    ) -> _Trajectory:
        self.durations = np.append(self.durations, [int(ramp_down_time / TICK_S)])
        self.user_programs = np.append(self.user_programs, 8)
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
    distances: dict,
) -> tuple[dict[Motor, npt.NDArray[np.float64]], dict[Motor, npt.NDArray[np.float64]]]:
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
                motor_info.motor_cs_index[motor],
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
    entry_velocities: dict[Motor, np.float64] = {}
    exit_velocities: dict[Motor, np.float64] = {}
    distances: dict[Motor, float] = {}
    for motor in motors:
        #            x
        #        x       x
        #    x               x
        #    vl  vlp vp  vpu vu
        # Given distances from Frame, lower, midpoint, upper, calculate
        # velocity at entry (vl) or exit (vu) of point by extrapolation
        entry_lower_upper_distance = (
            slice.upper[motor][gap - 1] - slice.lower[motor][gap - 1]
        )
        exit_lower_upper_distance = slice.upper[motor][gap] - slice.lower[motor][gap]

        start_midpoint_velocity = entry_lower_upper_distance / (
            2 * half_durations[gap - 1]
        )
        end_midpoint_velocity = exit_lower_upper_distance / (2 * half_durations[gap])

        # For entry, halfway point is vlp, so calculate dlp
        lower_midpoint_distance = (
            slice.midpoints[motor][gap - 1] - slice.lower[motor][gap - 1]
        )
        # For exit, halfway point is vpu, so calculate dpu
        midpoint_upper_distance = slice.upper[motor][gap] - slice.midpoints[motor][gap]

        # Extrapolate to get our entry or exit velocity
        # For example:
        # (vl + vp) / 2 = vlp
        # so vl = 2 * vlp - vp
        # where vlp = dlp / (t/2)
        # Therefore, velocity from point just before gap
        entry_velocities[motor] = (
            2 * (lower_midpoint_distance / half_durations[gap - 1])
            - start_midpoint_velocity
        )

        # Velocity from point just after gap
        exit_velocities[motor] = (
            2 * (midpoint_upper_distance / half_durations[gap - 1])
            - end_midpoint_velocity
        )

        # Travel distance across gap
        distances[motor] = slice.lower[motor][gap] - slice.upper[motor][gap - 1]
        if np.isclose(distances[motor], 0.0, atol=1e-12):
            distances[motor] = 0.0

    return entry_velocities, exit_velocities, distances


def _calculate_profile_from_velocities(
    motors: list[Motor],
    time_arrays: dict[Motor, npt.NDArray[np.float64]],
    velocity_arrays: dict[Motor, npt.NDArray[np.float64]],
    current_positions: dict[Motor, npt.NDArray[np.float64]],
) -> GapSegment:
    """Convert per-axis time/velocity profiles into aligned time/position profiles."""
    # All unique non‑zero time points across all axes
    combined_times = np.unique(np.concatenate(list(time_arrays.values())))
    combined_times = np.sort(combined_times)[1:]  # drop t=0
    num_intervals = len(combined_times)

    # Convert absolute times to interval durations
    time_intervals = np.diff(np.concatenate(([0.0], combined_times))).tolist()

    turnaround_profile: dict[Motor, npt.NDArray[np.float64]] = {}
    turnaround_velocity: dict[Motor, npt.NDArray[np.float64]] = {}

    for motor in motors:
        axis_times = time_arrays[motor]
        axis_vels = velocity_arrays[motor]
        pos = current_positions[motor]
        prev_vel = axis_vels[0]
        time_since_axis_point = 0.0
        axis_idx = 1  # index into this axis's profile

        turnaround_profile[motor] = np.empty(num_intervals, dtype=np.float64)
        turnaround_velocity[motor] = np.empty(num_intervals, dtype=np.float64)

        for i, dt in enumerate(time_intervals):
            next_vel = axis_vels[axis_idx]
            prev_axis_vel = axis_vels[axis_idx - 1]
            axis_dt = axis_times[axis_idx] - axis_times[axis_idx - 1]

            if np.isclose(combined_times[i], axis_times[axis_idx]):
                # Exact match with a defined velocity point
                this_vel = next_vel
                axis_idx += 1
                time_since_axis_point = 0.0
            else:
                # Interpolate between velocity points
                time_since_axis_point += dt
                frac = time_since_axis_point / axis_dt
                this_vel = prev_axis_vel + frac * (next_vel - prev_axis_vel)

            delta_pos = 0.5 * (prev_vel + this_vel) * dt
            pos += delta_pos
            prev_vel = this_vel

            turnaround_profile[motor][i] = pos
            turnaround_velocity[motor][i] = this_vel

    return GapSegment(
        turnaround_profile,
        turnaround_velocity,
        time_intervals,
        len(turnaround_profile),
    )
