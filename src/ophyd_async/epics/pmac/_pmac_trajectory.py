import time
from math import ceil
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
from ophyd_async.epics.pmac import Pmac, PmacMotor

TICK_S = 0.000001
MAX_MOVE_TIME = 4.0


class PmacTrajInfo(BaseModel):
    spec: Spec[PmacMotor | Literal["DURATION"]] = Field(default=None)
    combine_linear_points: bool = Field(default=False)


class PmacTrajectoryTriggerLogic(FlyerController[PmacTrajInfo]):
    """Device that moves a PMAC Motor record"""

    def __init__(self, pmac: Pmac) -> None:
        # Make a dict of which motors are for which cs axis
        self.pmac = pmac

    async def prepare(self, value: PmacTrajInfo):
        # initialise use_axis values to False
        for i in range(len("ABCUVWXYZ")):
            await self.pmac.use_axis[i + 1].set(False)

        path = Path(value.spec.calculate())
        chunk = path.consume()
        gaps = self._calculate_gaps(chunk)
        if gaps[0] == 0:
            gaps = np.delete(gaps, 0)
        scan_size = len(chunk)

        cs_ports = set()
        positions: dict[int, npt.NDArray[np.float64]] = {}
        velocities: dict[int, npt.NDArray[np.float64]] = {}
        cs_axes: dict[PmacMotor, int] = {}
        time_array: npt.NDArray[np.float64] = np.empty(
            2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.float64
        )
        user_array: npt.NDArray[np.int32] = np.empty(
            2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.int32
        )
        # Which Axes are in use?
        scan_axes = chunk.axes()
        for axis in scan_axes:
            if axis != "DURATION":
                cs_port, cs_index = await self.get_cs_info(axis)
                # Initialise numpy arrays for Positions, velocities and time within dict
                # for each axis in scan
                positions[cs_index] = np.empty(
                    2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.float64
                )
                velocities[cs_index] = np.empty(
                    2 * scan_size + ((len(gaps) + 1) * 5) + 1, dtype=np.float64
                )
                cs_ports.add(cs_port)
                cs_axes[axis] = cs_index
        assert len(cs_ports) == 1, "Motors in more than one CS"
        cs_port = cs_ports.pop()
        self.scantime = sum(chunk.midpoints["DURATION"])

        # Calc Velocity

        gaps = np.append(gaps, scan_size)
        start = 0
        added_point = 0

        # Starting points
        for axis in scan_axes:
            if axis != "DURATION":
                positions[cs_axes[axis]][start] = chunk.lower[axis][start]
                positions[cs_axes[axis]][start + 1] = chunk.upper[axis][start]
                # Set veloci
                velocities[cs_axes[axis]][start : start + 2] = np.repeat(
                    (chunk.upper[axis][start] - chunk.lower[axis][start])
                    / chunk.midpoints["DURATION"][start],
                    2,
                    axis=0,
                )
            else:
                # Half the time per point and duplicate the values
                # for interleaved positions
                time_array[start] = 0
                time_array[start + 1] = chunk.midpoints["DURATION"][start] / TICK_S
                user_array[start] = 1
                user_array[start + 1] = 1
        start = 1
        profile_index = 2 * start
        for gap in gaps:
            profile_start = profile_index
            profile_gap = (2 * gap) + added_point
            for axis in scan_axes:
                if value.combine_linear_points:
                    liner_move_time = sum(chunk.midpoints["DURATION"][start:gap])
                    if liner_move_time > MAX_MOVE_TIME:
                        nsplit = int(liner_move_time / MAX_MOVE_TIME) + 1
                    else:
                        nsplit = 2
                    linear_step = (
                        chunk.upper[axis][gap - 1] - chunk.midpoints[axis][start]
                    ) / nsplit
                    if axis != "DURATION":
                        for index in range(nsplit):
                            positions[cs_axes[axis]][profile_start + index] = (
                                chunk.midpoints[axis][start]
                                + (linear_step * (index + 1))
                            )
                        velocities[cs_axes[axis]][
                            profile_start : profile_start + nsplit
                        ] = np.repeat(
                            (chunk.upper[axis][start] - chunk.lower[axis][start])
                            / chunk.midpoints["DURATION"][start],
                            nsplit,
                        )
                    else:
                        time_array[profile_start : profile_start + nsplit] = ceil(
                            liner_move_time / ((nsplit) * TICK_S)
                        )
                        user_array[profile_start : profile_start + nsplit] = 1
                    profile_index = profile_start + nsplit
                else:
                    if axis != "DURATION":
                        # Interleave Midpoints and upper points into position array
                        positions[cs_axes[axis]][profile_start:profile_gap:2] = (
                            chunk.midpoints[axis][start:gap]
                        )
                        positions[cs_axes[axis]][
                            profile_start + 1 : profile_gap : 2
                        ] = chunk.upper[axis][start:gap]
                        # Duplicate velocity values for interleaved positions
                        velocities[cs_axes[axis]][profile_start:profile_gap] = (
                            np.repeat(
                                (
                                    chunk.upper[axis][start:gap]
                                    - chunk.lower[axis][start:gap]
                                )
                                / chunk.midpoints["DURATION"][start:gap],
                                2,
                                axis=0,
                            )
                        )
                    else:
                        # Half the time per point and duplicate the values
                        # for interleaved positions
                        time_array[profile_start:profile_gap] = np.repeat(
                            chunk.midpoints["DURATION"][start:gap] / (2 * TICK_S), 2
                        )
                        user_array[profile_start:profile_gap] = 1
                    profile_index = profile_gap
            if gap < scan_size:
                # Create Position, velocity and time arrays for the gap
                pos_gap, vel_gap, time_gap = await get_gap_profile(chunk, gap)
                len_gap = len(time_gap)
                for axis in scan_axes:
                    if axis != "DURATION":
                        positions[cs_axes[axis]][
                            profile_index : profile_index + len_gap
                        ] = pos_gap[axis]
                        velocities[cs_axes[axis]][
                            profile_index : profile_index + len_gap
                        ] = vel_gap[axis]

                    else:
                        time_array[profile_index : profile_index + len_gap] = time_gap
                        user_array[profile_index : profile_index + len_gap - 1] = 2
                        user_array[profile_index + len_gap - 1] = 1

                added_point += len_gap
                profile_index += len_gap
            start = gap

        # Calculate Starting and end Position to allow ramp up and trail off velocity
        self.initial_pos = {}
        run_up_time = 0
        final_time = 0
        profile_length = profile_index
        for axis in scan_axes:
            if axis != "DURATION":
                run_up_disp, run_up_t = await ramp_up_velocity_pos(
                    axis,
                    0,
                    velocities[cs_axes[axis]][0],
                )
                self.initial_pos[cs_axes[axis]] = (
                    positions[cs_axes[axis]][0] - run_up_disp
                )
                # trail off position and tim
                if (
                    velocities[cs_axes[axis]][0]
                    == velocities[cs_axes[axis]][profile_length - 1]
                ):
                    final_pos = (
                        positions[cs_axes[axis]][profile_length - 1] + run_up_disp
                    )
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

        for axis in scan_axes:
            if axis != "DURATION":
                await self.pmac.profile_cs_name.set(cs_port)
                await self.pmac.points_to_build.set(profile_length)
                await self.pmac.use_axis[cs_axes[axis] + 1].set(True)
                await self.pmac.positions[cs_axes[axis] + 1].set(
                    positions[cs_axes[axis]][:profile_length],
                )
                await self.pmac.velocities[cs_axes[axis] + 1].set(
                    velocities[cs_axes[axis]][:profile_length]
                )
            else:
                await self.pmac.time_array.set(time_array[:profile_length])
                await self.pmac.user_array.set(user_array[:profile_length])

        # MOVE TO START
        for axis in scan_axes:
            if axis != "DURATION":
                await axis.set(self.initial_pos[cs_axes[axis]])

        # Set PMAC to use Velocity Array
        await self.pmac.profile_calc_vel.set(False)
        await self.pmac.build_profile.set(True)
        self._fly_start = time.monotonic()

    async def kickoff(self):
        self.status = await self.pmac.execute_profile.set(
            True, timeout=self.scantime + 1
        )

    async def stop(self):
        await self.pmac.profile_abort.set(True)

    async def complete(self):
        await wait_for_value(
            self.pmac.execute_profile, False, timeout=self.scantime + 11
        )

    async def get_cs_info(self, motor: PmacMotor) -> tuple[str, int]:
        output_link = await motor.output_link.get_value()
        # Split "@asyn(PORT,num)" into ["PORT", "num"]
        split = output_link.split("(")[1].rstrip(")").split(",")
        cs_port = split[0].strip()
        if "CS" in cs_port:
            # Motor is compound
            cs_index = int(split[1].strip()) - 1
        else:
            # Raw Motor
            cs_port = await motor.cs_port.get_value()
            cs_axis = await motor.cs_axis.get_value()
            cs_index = "ABCUVWXYZ".index(cs_axis)

        return cs_port, cs_index

    def _calculate_gaps(self, chunk: Frames[PmacMotor]):
        inds = np.argwhere(chunk.gap)
        if len(inds) == 0:
            return [len(chunk)]
        else:
            return inds


async def ramp_up_velocity_pos(
    motor: PmacMotor,
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
    axis: PmacMotor,
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


async def get_gap_profile(chunk: Frames[PmacMotor], gap: int):
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
    chunk: Frames[PmacMotor],
    gap: int,
    min_time: float = 0.002,
    min_interval: float = 0.002,
):
    """Make consistent time and velocity arrays for each axis

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
) -> dict[PmacMotor, float]:
    """Find the velocities of each axis over the entry/exit of current point"""
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
            assert ((abs(velocity) - max_velocity) / max_velocity < 1e-6).all(), (
                f"Velocity {velocity} invalid for {axis.name} with "
                f"max_velocity {max_velocity}"
            )
            velocities[axis] = velocity
    return velocities


async def calculate_profile_from_velocities(
    chunk: Frames[PmacMotor],
    time_arrays: dict[PmacMotor, npt.NDArray[np.float64]],
    velocity_arrays: dict[PmacMotor, npt.NDArray[np.float64]],
    current_positions: dict[PmacMotor, npt.NDArray[np.float64]],
) -> tuple[
    dict[PmacMotor, npt.NDArray[np.float64]],
    dict[PmacMotor, npt.NDArray[np.float64]],
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
    turnaround_profile: dict[PmacMotor, npt.NDArray[np.float64]] = {}
    turnaround_velocity: dict[PmacMotor, npt.NDArray[np.float64]] = {}

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
