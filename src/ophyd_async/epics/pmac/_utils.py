from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from scanspec.core import Slice

from ophyd_async.core import gather_dict
from ophyd_async.epics.motor import Motor

from ._pmac_io import CS_LETTERS, PmacIO


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
