from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from numpy import float64
from scanspec.core import Slice
from velocity_profile.velocityprofile import VelocityProfile as vp

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

        scan_size = len(slice)
        gaps: list[int] = np.where(slice.gap)[0].tolist()
        gaps.append(len(slice))
        motors = slice.axes()

        positions: dict[Motor, npt.NDArray[np.float64]] = {}
        velocities: dict[Motor, npt.NDArray[np.float64]] = {}

        # Initialise arrays
        trajectory_size = ((2 * scan_size) + 1) + ((len(gaps) - 2) * 4)
        positions = {motor: np.empty(trajectory_size, float) for motor in motors}
        velocities = {motor: np.empty(trajectory_size, float) for motor in motors}
        durations: npt.NDArray[np.float64] = np.empty(trajectory_size, float)
        user_programs: npt.NDArray[np.int32] = np.ones(trajectory_size, float)

        # Ramp up time for start of collection window
        durations[0] = int(ramp_up_time / TICK_S)

        half_durations = slice_duration / 2

        # Precompute gaps
        gap_points = {}
        for gap in gaps[1:-1]:
            # Get entry velocities, exit velocities, and distances across gap
            start_velocities, end_velocities, distances = _get_start_and_end_velocities(
                motors, slice, half_durations, gap
            )

            # Get velocity and time profiles across gap
            time_arrays, velocity_arrays = _get_velocity_profile(
                motors, motor_info, start_velocities, end_velocities, distances
            )

            start_positions = {motor: slice.upper[motor][gap - 1] for motor in motors}

            # Calculate gap position, velocity, and time profiles from
            # velocity and time profiles
            (
                gap_positions,
                gap_velocities,
                gap_durations,
            ) = _calculate_profile_from_velocities(
                motors, time_arrays, velocity_arrays, start_positions
            )

            gap_points[gap] = {
                "positions": gap_positions,
                "velocities": gap_velocities,
                "durations": gap_durations,
            }

        # Fill trajectory with gaps
        for motor in motors:
            gap_offset = 0
            for start_idx, end_idx in zip(gaps[:-1], gaps[1:], strict=False):
                # Interleave points and offset by added pvt points
                start_traj = 2 * start_idx + gap_offset
                end_traj = 2 * end_idx + gap_offset

                # Lower bound at the segment start
                positions[motor][start_traj] = slice.lower[motor][start_idx]

                # Fill mids into odd slots, uppers into even slots
                positions[motor][start_traj + 1 : (end_traj) + 1 : 2] = slice.midpoints[
                    motor
                ][start_idx:end_idx]
                positions[motor][start_traj + 2 : (end_traj) + 1 : 2] = slice.upper[
                    motor
                ][start_idx:end_idx]

                # For velocities we will need the relative distances
                mid_to_upper_velocities = (
                    slice.upper[motor][start_idx:end_idx]
                    - slice.midpoints[motor][start_idx:end_idx]
                ) / half_durations[start_idx:end_idx]
                lower_to_mid_velocities = (
                    slice.midpoints[motor][start_idx:end_idx]
                    - slice.lower[motor][start_idx:end_idx]
                ) / half_durations[start_idx:end_idx]

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

                user_programs[start_traj:end_traj] = 1

                durations[start_traj + 1 : end_traj + 1] = np.repeat(
                    (half_durations[start_idx:end_idx] / TICK_S).astype(int), 2
                )

                if gap_points.get(end_idx):
                    # How many gap points do we need to add
                    num_gap_points = len(gap_points[end_idx]["positions"][motor])
                    # Update how many gap points we've added so far
                    gap_offset += num_gap_points
                    # Insert gap points into end of collection window
                    positions[motor][end_traj + 1 : end_traj + 1 + num_gap_points] = (
                        gap_points[end_idx]["positions"][motor]
                    )
                    velocities[motor][end_traj + 1 : end_traj + 1 + num_gap_points] = (
                        gap_points[end_idx]["velocities"][motor]
                    )
                    durations[end_traj + 1 : end_traj + 1 + num_gap_points] = (
                        np.array(gap_points[end_idx]["durations"]) / TICK_S
                    ).astype(int)
                    # Set user program to 2 for gap points
                    user_programs[end_traj + 1 : end_traj + num_gap_points] = 2

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
    start_velocities: dict,
    end_velocities: dict,
    distances: dict,
):
    profiles: dict[Motor, vp] = {}
    time_arrays = {}
    velocity_arrays = {}

    min_time = MIN_TURNAROUND
    iterations = 2

    while iterations > 0:
        new_min_time = 0.0  # reset for this iteration

        for motor in motors:
            # Build profile for this motor
            p = vp(
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

    raise ValueError("Can't get a consistent time in 2 iterations")


def _calculate_profile_from_velocities(
    motors: list[Motor],
    time_arrays: dict[Motor, npt.NDArray[np.float64]],
    velocity_arrays: dict[Motor, npt.NDArray[np.float64]],
    current_positions: dict[Motor, npt.NDArray[np.float64]],
) -> tuple[
    dict[Motor, npt.NDArray[np.float64]],
    dict[Motor, npt.NDArray[np.float64]],
    list[float],
]:
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
        axis_pt = 1  # index into this axis's profile

        turnaround_profile[motor] = np.empty(num_intervals, dtype=np.float64)
        turnaround_velocity[motor] = np.empty(num_intervals, dtype=np.float64)

        for i, dt in enumerate(time_intervals):
            next_vel = axis_vels[axis_pt]
            prev_axis_vel = axis_vels[axis_pt - 1]
            axis_dt = axis_times[axis_pt] - axis_times[axis_pt - 1]

            if np.isclose(combined_times[i], axis_times[axis_pt]):
                # Exact match with a defined velocity point
                this_vel = next_vel
                axis_pt += 1
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

    return turnaround_profile, turnaround_velocity, time_intervals


def _get_start_and_end_velocities(
    motors: list[Motor], slice: Slice, half_durations: npt.NDArray[float64], gap: int
):
    start_velocities = {}
    end_velocities = {}
    distances = {}
    for motor in motors:
        # Velocity from point just before gap (exit velocity)
        start_velocities[motor] = 2 * (
            slice.upper[motor][gap - 1] - slice.midpoints[motor][gap - 1]
        ) / half_durations[gap - 1] - (
            slice.upper[motor][gap - 1] - slice.lower[motor][gap - 1]
        ) / (half_durations[gap - 1] * 2)

        # Velocity from point just after gap
        end_velocities[motor] = 2 * (
            slice.midpoints[motor][gap] - slice.lower[motor][gap]
        ) / half_durations[gap] - (
            slice.upper[motor][gap] - slice.lower[motor][gap]
        ) / (half_durations[gap] * 2)

        # Travel distance across gap
        distances[motor] = slice.lower[motor][gap] - slice.upper[motor][gap - 1]
        if np.isclose(distances[motor], 0.0, atol=1e-12):
            distances[motor] = 0.0

    return start_velocities, end_velocities, distances
