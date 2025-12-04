from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scanspec.core import Slice

from ophyd_async.core import gather_dict
from ophyd_async.epics.motor import Motor

from ._pmac_io import CS_INDEX, PmacIO

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001
MIN_TURNAROUND = 0.002
MIN_INTERVAL = 0.002

# Regex to parse outlink strings of the form "@asyn(PMAC1CS2, 7)"
# returning PMAC1CS2 and 7
# https://regex101.com/r/Mu9XpO/1
OUTLINK_REGEX = re.compile(r"^\@asyn\(([^,]+),\s*(\d+)\)$")


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
        is_raw_motor = [motor in pmac.motor_assignment_index for motor in motors]
        if all(is_raw_motor):
            # Get the CS port, number and axis letter from the PVs for the raw motor
            assignments = {
                motor: pmac.assignment[pmac.motor_assignment_index[motor]]
                for motor in motors
            }
            cs_ports, cs_numbers, cs_axis_letters = await asyncio.gather(
                gather_dict(
                    {motor: assignments[motor].cs_port.get_value() for motor in motors}
                ),
                gather_dict(
                    {
                        motor: assignments[motor].cs_number.get_value()
                        for motor in motors
                    }
                ),
                gather_dict(
                    {
                        motor: assignments[motor].cs_axis_letter.get_value()
                        for motor in motors
                    }
                ),
            )
            # Translate axis letters to cs_index and check for duplicates
            motor_cs_index: dict[Motor, int] = {}
            for motor, cs_axis_letter in cs_axis_letters.items():
                if not cs_axis_letter:
                    raise ValueError(
                        f"Motor {motor.name} does not have an axis assignment."
                    )
                try:
                    # 1 indexed to match coord
                    index = CS_INDEX[cs_axis_letter]
                except KeyError as err:
                    raise ValueError(
                        f"Motor {motor.name} assigned to '{cs_axis_letter}' "
                        f"but must be assigned to one of '{','.join(CS_INDEX)}'"
                    ) from err
                if index in motor_cs_index.values():
                    raise ValueError(
                        f"Motor {motor.name} assigned to '{cs_axis_letter}' "
                        "but another motor is already assigned to this axis."
                    )
                motor_cs_index[motor] = index
        elif not any(is_raw_motor):
            # Get CS numbers from all the cs ports and output links for the CS motors
            output_links, cs_lookup = await asyncio.gather(
                gather_dict({motor: motor.output_link.get_value() for motor in motors}),
                gather_dict(
                    {
                        cs_number: cs.cs_port.get_value()
                        for cs_number, cs in pmac.coord.items()
                    }
                ),
            )
            # Create a reverse lookup from cs_port to cs_number
            cs_reverse_lookup = {
                cs_port: cs_number for cs_number, cs_port in cs_lookup.items()
            }
            cs_ports: dict[Motor, str] = {}
            cs_numbers: dict[Motor, int] = {}
            motor_cs_index: dict[Motor, int] = {}
            # Populate the cs_ports, cs_numbers and motor_cs_index dicts from outlinks
            for motor, output_link in output_links.items():
                match = OUTLINK_REGEX.match(output_link)
                if not match:
                    raise ValueError(
                        f"Motor {motor.name} has invalid output link '{output_link}'"
                    )
                cs_port, cs_index = match.groups()
                cs_ports[motor] = cs_port
                cs_numbers[motor] = cs_reverse_lookup[cs_port]
                motor_cs_index[motor] = int(cs_index)
        else:
            raise ValueError("Unable to use raw motors and CS motors in the same scan")

        # check if the values in cs_port and cs_number are the same
        cs_ports_set = set(cs_ports.values())
        if len(cs_ports_set) != 1:
            raise RuntimeError(
                "Failed to fetch common CS port."
                "Motors passed are assigned to multiple CS ports:"
                f"{list(cs_ports_set)}"
            )
        cs_numbers_set = set(cs_numbers.values())
        if len(cs_numbers_set) != 1:
            raise RuntimeError(
                "Failed to fetch common CS number."
                "Motors passed are assigned to multiple CS numbers:"
                f"{list(cs_numbers_set)}"
            )

        # Get the velocities and acceleration rates for each motor
        max_velocity, acceleration_time = await asyncio.gather(
            gather_dict({motor: motor.max_velocity.get_value() for motor in motors}),
            gather_dict(
                {motor: motor.acceleration_time.get_value() for motor in motors}
            ),
        )
        motor_acceleration_rate = {
            motor: max_velocity[motor] / acceleration_time[motor] for motor in motors
        }
        return _PmacMotorInfo(
            cs_port=cs_ports_set.pop(),
            cs_number=cs_numbers_set.pop(),
            motor_cs_index=motor_cs_index,
            motor_acceleration_rate=motor_acceleration_rate,
            motor_max_velocity=max_velocity,
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
