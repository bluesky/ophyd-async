import time
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field
from scanspec.specs import Frames, Path, Spec
from velocity_profile import velocityprofile as vp

from ophyd_async.core import (
    FlyerController,
    wait_for_value,
)
from ophyd_async.epics.pmac import PmacAxisIO, PmacCoordIO, PmacIO

TICK_S = 0.000001
MAX_MOVE_TIME = 4.0


@dataclass
class Trajectory:
    position_axes: list[PmacAxisIO | PmacCoordIO]
    cs_port: str
    profile_length: int
    cs_axes: dict[PmacAxisIO | PmacCoordIO, int]
    positions: dict[int, npt.NDArray[np.float64]]
    initial_pos: dict[int, npt.NDArray[np.float64]]
    velocities: dict[int, npt.NDArray[np.float64]]
    time_array: npt.NDArray[np.float64]
    user_array: npt.NDArray[np.int32]


class PmacTrajInfo(BaseModel):
    spec: Spec[PmacAxisIO | PmacCoordIO | Literal["DURATION"]] = Field(default=None)
    combine_linear_points: bool = Field(default=False)


class PmacTrajectoryTriggerLogic(FlyerController[PmacTrajInfo]):
    """Device that moves a PMAC Motor record."""

    def __init__(self, pmac: PmacIO) -> None:
        # Make a dict of which motors are for which cs axis
        self.pmac = pmac

    async def prepare(self, value: PmacTrajInfo):
        # initialise use_axis values to False
        for i in range(len("ABCUVWXYZ")):
            await self.pmac.trajectory.use_axis[i + 1].set(False)

        trajectory = await self.prepare_trajectory(value.spec)

        for axis in trajectory.position_axes:
            await self.pmac.trajectory.profile_cs_name.set(trajectory.cs_port)
            await self.pmac.trajectory.points_to_build.set(trajectory.profile_length)
            await self.pmac.trajectory.use_axis[trajectory.cs_axes[axis] + 1].set(True)
            # TODO: Should this be truncated to profile_length before now?
            await self.pmac.trajectory.positions[trajectory.cs_axes[axis] + 1].set(
                trajectory.positions[trajectory.cs_axes[axis]][
                    : trajectory.profile_length
                ],
            )
            await self.pmac.trajectory.velocities[trajectory.cs_axes[axis] + 1].set(
                trajectory.velocities[trajectory.cs_axes[axis]][
                    : trajectory.profile_length
                ]
            )

        await self.pmac.trajectory.time_array.set(
            trajectory.time_array[: trajectory.profile_length]
        )
        await self.pmac.trajectory.user_array.set(
            trajectory.user_array[: trajectory.profile_length]
        )

        # Move to start
        cs_port_number = int(trajectory.cs_port[-1])
        await self.pmac.coord[cs_port_number].defer_moves.set(True)
        for axis in trajectory.position_axes:
            cs_axis = trajectory.cs_axes[axis]
            await (
                self.pmac.coord[cs_port_number]
                .cs_axis_setpoint[cs_axis]
                .set(trajectory.initial_pos[cs_axis])
            )
        await self.pmac.coord[cs_port_number].defer_moves.set(False)

        # Set PMAC to use Velocity Array
        await self.pmac.trajectory.calculate_velocities.set(False)
        await self.pmac.trajectory.build_profile.set(True)
        self._fly_start = time.monotonic()

    async def prepare_trajectory(self, scanspec: Spec) -> Trajectory:
        path = Path(scanspec.calculate())
        scan_slice = path.consume()
        scan_size = len(scan_slice)

        gap_indices = self._find_gap_indices(scan_slice)
        position_axes: list[PmacAxisIO | PmacCoordIO] = [
            axis for axis in scan_slice.axes() if axis != "DURATION"
        ]
        duration_axis = scan_slice.midpoints["DURATION"]
        self.scantime = sum(duration_axis)

        cs_ports = set()
        positions: dict[int, npt.NDArray[np.float64]] = {}
        velocities: dict[int, npt.NDArray[np.float64]] = {}
        cs_axes: dict[PmacAxisIO | PmacCoordIO, int] = {}
        time_array: npt.NDArray[np.float64] = np.empty(
            2 * scan_size + ((len(gap_indices) + 1) * 5) + 1, dtype=np.float64
        )
        user_array: npt.NDArray[np.int32] = np.empty(
            2 * scan_size + ((len(gap_indices) + 1) * 5) + 1, dtype=np.int32
        )

        # Which Axes are in use?
        for axis in position_axes:
            cs_port, cs_index = await self.get_cs_info(axis)
            # Initialise numpy arrays for Positions, velocities and time within dict
            # for each axis in scan
            positions[cs_index] = np.empty(
                2 * scan_size + ((len(gap_indices) + 1) * 5) + 1, dtype=np.float64
            )
            velocities[cs_index] = np.empty(
                2 * scan_size + ((len(gap_indices) + 1) * 5) + 1, dtype=np.float64
            )
            cs_ports.add(cs_port)
            cs_axes[axis] = cs_index

        assert len(cs_ports) == 1, "Motors in more than one CS"  # noqa
        cs_port = cs_ports.pop()

        # TODO:
        # - Move everything above here should move out and be passed in?
        #   - Initialise a Trajectory and pass in
        #   Move some preamble back to prepare
        # - Might be cleaner if this method does not know about PmacIO, only indices
        #   - Pass in a list of active CS indices
        #   - positions[cs_axes[axis]] -> positions[cs_idx]
        # - This method should be static if possible
        #   - Pass scantime back via Trajectory

        # Starting points

        start = 0
        for axis in position_axes:
            positions[cs_axes[axis]][start] = scan_slice.lower[axis][start]
            positions[cs_axes[axis]][start + 1] = scan_slice.upper[axis][start]
            # Set veloci
            velocities[cs_axes[axis]][start : start + 2] = np.repeat(
                (scan_slice.upper[axis][start] - scan_slice.lower[axis][start])
                / duration_axis[start],
                2,
                axis=0,
            )

        # Half the time per point and duplicate the values
        # for interleaved positions
        time_array[start] = 0
        time_array[start + 1] = duration_axis[start] / TICK_S
        user_array[start] = 1
        user_array[start + 1] = 1

        # Add points for gaps

        gap_indices = np.append(gap_indices, scan_size)
        start = 1
        added_point = 0
        profile_index = 2 * start
        for gap in gap_indices:
            profile_start = profile_index
            profile_gap = (2 * gap) + added_point
            for axis in position_axes:
                # Interleave Midpoints and upper points into position array
                positions[cs_axes[axis]][profile_start:profile_gap:2] = (
                    scan_slice.midpoints[axis][start:gap]
                )
                positions[cs_axes[axis]][profile_start + 1 : profile_gap : 2] = (
                    scan_slice.upper[axis][start:gap]
                )

                # Duplicate velocity values for interleaved positions
                velocities[cs_axes[axis]][profile_start:profile_gap] = np.repeat(
                    (
                        scan_slice.upper[axis][start:gap]
                        - scan_slice.lower[axis][start:gap]
                    )
                    / duration_axis[start:gap],
                    2,
                    axis=0,
                )

            # Half the time per point and duplicate the values
            # for interleaved positions
            time_array[profile_start:profile_gap] = np.repeat(
                duration_axis[start:gap] / (2 * TICK_S), 2
            )
            user_array[profile_start:profile_gap] = 1

            profile_index = profile_gap

            # TODO: Can we not do this and handle the extra point in another way?
            if gap < scan_size:  # If this isn't the extra gap for the last point
                # Create Position, velocity and time arrays for the gap
                pos_gap, vel_gap, time_gap = await get_gap_profile(scan_slice, gap)
                len_gap = len(time_gap)
                for axis in position_axes:
                    positions[cs_axes[axis]][
                        profile_index : profile_index + len_gap
                    ] = pos_gap[axis]
                    velocities[cs_axes[axis]][
                        profile_index : profile_index + len_gap
                    ] = vel_gap[axis]

                time_array[profile_index : profile_index + len_gap] = time_gap
                user_array[profile_index : profile_index + len_gap - 1] = 2
                user_array[profile_index + len_gap - 1] = 1

                added_point += len_gap
                profile_index += len_gap

            start = gap

        # Calculate Starting and end Position to allow ramp up and trail off velocity

        initial_pos = {}
        run_up_time = 0
        final_time = 0
        profile_length = profile_index
        for axis in position_axes:
            run_up_disp, run_up_t = await ramp_up_velocity_pos(
                axis,
                0,
                velocities[cs_axes[axis]][0],
            )
            initial_pos[cs_axes[axis]] = positions[cs_axes[axis]][0] - run_up_disp

            # trail off position and tim
            if (
                velocities[cs_axes[axis]][0]
                == velocities[cs_axes[axis]][profile_length - 1]
            ):
                final_pos = positions[cs_axes[axis]][profile_length - 1] + run_up_disp
                final_time = run_up_t
            else:
                ramp_down_disp, ramp_down_time = await ramp_up_velocity_pos(
                    axis,
                    velocities[cs_axes[axis]][profile_length - 1],
                    0,
                )
                final_pos = (
                    positions[cs_axes[axis]][profile_length - 1] + ramp_down_disp
                )
                final_time = max(ramp_down_time, final_time)

            positions[cs_axes[axis]][profile_length] = final_pos
            velocities[cs_axes[axis]][profile_length] = 0
            run_up_time = max(run_up_time, run_up_t)

        self.scantime += run_up_time + final_time
        time_array[0] = int(run_up_time / TICK_S)
        time_array[profile_length] = int(final_time / TICK_S)
        user_array[profile_length] = 8
        profile_length += 1

        return Trajectory(
            position_axes,
            cs_port,
            profile_length,
            cs_axes,
            positions,
            initial_pos,
            velocities,
            time_array,
            user_array,
        )

    async def kickoff(self):
        self.status = await self.pmac.trajectory.execute_profile.set(
            True, timeout=self.scantime + 1
        )

    async def stop(self):
        await self.pmac.trajectory.abort_profile.set(True)

    async def complete(self):
        await wait_for_value(
            self.pmac.trajectory.execute_profile, False, timeout=self.scantime + 11
        )

    async def get_cs_info(self, motor: PmacAxisIO | PmacCoordIO) -> tuple[str, int]:
        if isinstance(motor, PmacAxisIO):
            cs_port = await motor.cs_port.get_value()
            cs_axis = await motor.cs_axis_letter.get_value()
            cs_index = "ABCUVWXYZ".index(cs_axis)
        else:
            output_link = await motor.output_link.get_value()
            split = output_link.split("(")[1].rstrip(")").split(",")
            cs_port = split[0].strip()
            cs_index = int(split[1].strip()) - 1
        return cs_port, cs_index

    def _find_gap_indices(self, chunk: Frames[PmacAxisIO | PmacCoordIO]):
        """Find indices of scan points preceded by a gap."""
        gap_indices = np.argwhere(chunk.gap)

        # TODO: Why do we only add a gap to the end if there are no other gaps?
        if len(gap_indices) == 0:
            # Add gap to end
            gap_indices = [len(chunk)]

        # TODO: Why?
        if gap_indices[0] == 0:
            # Remove gam from start
            gap_indices = np.delete(gap_indices, 0)

        return gap_indices


async def ramp_up_velocity_pos(
    motor: PmacAxisIO | PmacCoordIO,
    start_velocity: float,
    end_velocity: float,
    ramp_time: float = 0,
    min_ramp_time: float = 0,
):
    # For the given motor return the displacement and time taken to get from one given
    # velocity to another
    acceleration_time = await motor.acceleration_time.get_value()
    max_velocity = await motor.max_velocity.get_value()
    accl = max_velocity / acceleration_time
    delta_v = abs(end_velocity - start_velocity)
    if ramp_time == 0:
        ramp_time = delta_v / accl
    if min_ramp_time:
        ramp_time = max(ramp_time, min_ramp_time)
    disp = 0.5 * (start_velocity + end_velocity) * ramp_time
    return [disp, ramp_time]


async def make_velocity_profile(
    axis: PmacAxisIO | PmacCoordIO,
    v1: float,
    v2: float,
    distance: float,
    min_time: float,
    min_interval: float = 0.002,
) -> vp.VelocityProfile:
    # Create the time and velocity arrays
    velocity_settle = 0
    max_vel = await axis.max_velocity.get_value()
    acc = max_vel / await axis.acceleration_time.get_value()
    p = vp.VelocityProfile(
        v1,
        v2,
        distance,
        min_time,
        acc,
        max_vel,
        velocity_settle,
        min_interval,
    )
    p.get_profile()
    return p


async def get_gap_profile(chunk: Frames[PmacAxisIO | PmacCoordIO], gap: int):
    # Work out the velocity profiles of how to move to the start
    # Turnaround can't be less than 2 ms
    prev_point = gap - 1
    min_turnaround = 0.002
    min_interval = 0.002
    time_arrays, velocity_arrays = await profile_between_points(
        chunk,
        gap,
        min_turnaround,
        min_interval,
    )

    start_positions = {}
    for axis in chunk.axes():
        start_positions[axis] = chunk.upper[axis][prev_point]

    # Work out the Position trajectories from these profiles
    (
        position_array,
        velocity_array,
        time_array,
    ) = await calculate_profile_from_velocities(
        chunk, time_arrays, velocity_arrays, start_positions
    )
    time_profile = np.empty(len(time_array), dtype=np.float64)
    for i in range(len(time_array)):
        time_profile[i] = int(time_array[i] / TICK_S)
    return position_array, velocity_array, time_profile


async def profile_between_points(
    chunk: Frames[PmacAxisIO | PmacCoordIO],
    gap: int,
    min_time: float = 0.002,
    min_interval: float = 0.002,
):
    """Make consistent time and velocity arrays for each axis.

    Try to create velocity profiles for all axes that all arrive at
    'distance' in the same time period. The profiles will contain the
    following points:-

    in the following description acceleration can be -ve or +ve depending
    on the relative sign of v1 and v2. fabs(vm) is <= maximum velocity
    - start point at 0 secs with velocity v1     start accelerating
    - middle velocity start                      reached speed vm
    - middle velocity end                        start accelerating
    - end point with velocity v2                 reached target speed

    Time at vm may be 0 in which case there are only 3 points and
    acceleration to v2 starts as soon as vm is reached.

    If the profile has to be stretched to achieve min_time then the
    the middle period at speed vm is extended accordingly.

    After generating all the profiles this function checks to ensure they
    have all achieved min_time. If not min_time is reset to the slowest
    profile and all profiles are recalculated.

    Note that for each profile the area under the velocity/time plot
    must equal 'distance'. The VelocityProfile library implements the maths
    to achieve this.
    """
    prev_point = gap - 1
    start_velocities = await point_velocities(chunk, prev_point)
    end_velocities = await point_velocities(chunk, gap, entry=False)

    p = None
    new_min_time = 0
    time_arrays = {}
    velocity_arrays = {}
    profiles = {}
    # The first iteration reveals the slowest profile. The second generates
    # all profiles with the slowest min_time
    iterations = 2
    while iterations > 0:
        for axis in chunk.axes():
            if axis != "DURATION":
                distance = chunk.lower[axis][gap] - chunk.upper[axis][prev_point]
                # If the distance is tiny, round to zero
                if np.isclose(distance, 0.0, atol=1e-12):
                    distance = 0.0
                p = await make_velocity_profile(
                    axis,
                    start_velocities[axis],
                    end_velocities[axis],
                    distance,
                    min_time,
                    min_interval,
                )
                # Absolute time values that we are at that velocity
                profiles[axis] = p
                new_min_time = max(new_min_time, p.t_total)
        if np.isclose(new_min_time, min_time):
            for axis in chunk.axes():
                if axis != "DURATION":
                    time_arrays[axis], velocity_arrays[axis] = profiles[
                        axis
                    ].make_arrays()
            return time_arrays, velocity_arrays
        else:
            min_time = new_min_time
            iterations -= 1
    raise ValueError("Can't get a consistent time in 2 iterations")


async def point_velocities(
    chunk: Frames[Any], index: int, entry: bool = True
) -> dict[PmacAxisIO | PmacCoordIO, float]:
    """Find the velocities of each axis over the entry/exit of current point."""
    velocities = {}
    for axis in chunk.axes():
        if axis != "DURATION":
            #            x
            #        x       x
            #    x               x
            #    vl  vlp vp  vpu vu
            # Given distances from Frame, lower, midpoint, upper, calculate
            # velocity at entry (vl) or exit (vu) of point by extrapolation
            dp = chunk.upper[axis][index] - chunk.lower[axis][index]
            vp = dp / chunk.midpoints["DURATION"][index]
            if entry:
                # Halfway point is vlp, so calculate dlp
                d_half = chunk.midpoints[axis][index] - chunk.lower[axis][index]
            else:
                # Halfway point is vpu, so calculate dpu
                d_half = chunk.upper[axis][index] - chunk.midpoints[axis][index]
            # Extrapolate to get our entry or exit velocity
            # (vl + vp) / 2 = vlp
            # so vl = 2 * vlp - vp
            # where vlp = dlp / (t/2)
            velocity = 4 * d_half / chunk.midpoints["DURATION"][index] - vp
            max_velocity = await axis.max_velocity.get_value()
            assert ((abs(velocity) - max_velocity) / max_velocity < 1e-6).all(), (  # noqa
                f"Velocity {velocity} invalid for {axis.name} with "
                f"max_velocity {max_velocity}"
            )
            velocities[axis] = velocity
    return velocities


async def calculate_profile_from_velocities(
    chunk: Frames[PmacAxisIO | PmacCoordIO],
    time_arrays: dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]],
    velocity_arrays: dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]],
    current_positions: dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]],
) -> tuple[
    dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]],
    dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]],
    list[int],
]:
    # at this point we have time/velocity arrays with 2-4 values for each
    # axis. Each time represents a (instantaneous) change in acceleration.
    # We want to translate this into a move profile (time/position).
    # Every axis profile must have a point for each of the times from
    # all axes combined

    # extract the time points from all axes
    t_list = []
    for time_array in time_arrays.values():
        t_list.extend(time_array)
    combined_times = np.array(t_list)
    combined_times = np.unique(combined_times)
    # remove the 0 time initial point
    combined_times = list(np.sort(combined_times))[1:]
    num_intervals = len(combined_times)

    # set up the time, mode and user arrays for the trajectory
    prev_time = 0
    time_intervals = []
    for t in combined_times:
        # times are absolute - convert to intervals
        time_intervals.append(t - prev_time)
        prev_time = t
    # generate the profile positions in a temporary dict:
    turnaround_profile: dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]] = {}
    turnaround_velocity: dict[PmacAxisIO | PmacCoordIO, npt.NDArray[np.float64]] = {}

    # Do this for each axis' velocity and time arrays
    for axis in chunk.axes():
        if axis != "DURATION":
            turnaround_profile[axis] = np.empty(num_intervals, dtype=np.float64)
            turnaround_velocity[axis] = np.empty(num_intervals, dtype=np.float64)
            axis_times = time_arrays[axis]
            axis_velocities = velocity_arrays[axis]
            prev_velocity = axis_velocities[0]
            position = current_positions[axis]
            # tracks the accumulated interpolated interval time since the
            # last axis velocity profile point
            time_interval = 0
            # At this point we have time/velocity arrays with multiple values
            # some of which align with the axis_times and some interleave.
            # We want to create a matching move profile of 'num_intervals'
            axis_pt = 1
            for i in range(num_intervals):
                axis_velocity = axis_velocities[axis_pt]
                axis_prev_velocity = axis_velocities[axis_pt - 1]
                axis_interval = axis_times[axis_pt] - axis_times[axis_pt - 1]

                if np.isclose(combined_times[i], axis_times[axis_pt]):
                    # this combined point matches the axis point
                    # use the axis velocity and move to the next axis point
                    this_velocity = axis_velocities[axis_pt]
                    axis_pt += 1
                    time_interval = 0
                else:
                    # this combined point is between two axis points,
                    # interpolate the velocity between those axis points
                    time_interval += time_intervals[i]
                    fraction = time_interval / axis_interval
                    dv = axis_velocity - axis_prev_velocity
                    this_velocity = axis_prev_velocity + fraction * dv

                part_position, _ = await ramp_up_velocity_pos(
                    axis, prev_velocity, this_velocity, time_intervals[i]
                )
                prev_velocity = this_velocity

                position += part_position
                turnaround_profile[axis][i] = position
                turnaround_velocity[axis][i] = this_velocity

    return turnaround_profile, turnaround_velocity, time_intervals
