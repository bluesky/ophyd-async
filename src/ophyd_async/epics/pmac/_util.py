import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from ophyd_async.core._utils import gather_dict
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac._pmac_io import PmacIO


@dataclass
class _PmacMotorInfo:
    cs_port: str
    cs_number: int
    motor_cs_index: dict[Motor, int]
    motor_acceleration_rate: dict[Motor, float]

    @classmethod
    async def from_motors(
        cls, pmac: PmacIO, motors: Sequence[Motor]
    ) -> "_PmacMotorInfo":
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
            motor_cs_index[motor] = "ABCUVWXYZ".index(cs_axes[motor])
            if len(set(motor_cs_index.values())) != len(motor_cs_index.items()):
                raise RuntimeError(
                    "Failed to fetch distinct CS Axes."
                    "Motors passed are assigned to the same CS Axis"
                )

        motor_acceleration_rate = {
            motor: float(velocities[motor]) / float(accls[motor])
            for motor in velocities
        }

        return _PmacMotorInfo(
            cs_port, cs_number, motor_cs_index, motor_acceleration_rate
        )
