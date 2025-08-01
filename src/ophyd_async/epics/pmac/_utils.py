from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scanspec.core import Slice

from ophyd_async.core import error_if_none, gather_dict
from ophyd_async.epics.motor import Motor

from ._pmac_io import CS_LETTERS, PmacIO

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001


@dataclass
class _Trajectory:
    positions: dict[Motor, np.ndarray]
    velocities: dict[Motor, np.ndarray]
    user_programs: npt.NDArray[np.int32]
    durations: npt.NDArray[np.float64]

    @classmethod
    def from_slice(cls, slice: Slice[Motor], ramp_up_time: float) -> _Trajectory:
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


@dataclass
class _PmacMotorInfo:
    cs_port: str
    cs_number: int
    motor_cs_index: dict[Motor, int]
    motor_acceleration_rate: dict[Motor, float]

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
            cs_port, cs_number, motor_cs_index, motor_acceleration_rate
        )


def calculate_ramp_position_and_duration(
    slice: Slice[Motor], motor_info: _PmacMotorInfo, is_up: bool
) -> tuple[dict[Motor, float], float]:
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

    max_ramp_time = max(ramp_times)

    motor_to_ramp_position = {}
    sign = -1 if is_up else 1
    for axis, v in velocities.items():
        ref_pos = slice.lower[axis][0] if is_up else slice.upper[axis][-1]
        displacement = 0.5 * v * max_ramp_time
        motor_to_ramp_position[axis] = ref_pos + sign * displacement

    return (motor_to_ramp_position, max_ramp_time)
