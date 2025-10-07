import asyncio
from copy import copy

import matplotlib.pyplot as plt
import numpy as np
from scanspec.core import Path
from scanspec.specs import Fly, Line, Spiral

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_trajectory_generation import (
    Trajectory,
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,
    calculate_ramp_position_and_duration,
)
from ophyd_async.testing import set_mock_value
from ruckig import InputParameter, OutputParameter, Result, Ruckig
from ruckig import Trajectory as RTrajectory


async def sim_motors():
    async with init_devices(mock=True):
        sim_x_motor = Motor("BLxxI-MO-STAGE-01:X")
        sim_y_motor = Motor("BLxxI-MO-STAGE-01:Y")
        sim_pmac = PmacIO(
            prefix="Test_PMAC",
            raw_motors=[sim_x_motor, sim_y_motor],
            coord_nums=[1],
        )

    pmac_x = sim_pmac.assignment[sim_pmac.motor_assignment_index[sim_x_motor]]
    pmac_y = sim_pmac.assignment[sim_pmac.motor_assignment_index[sim_y_motor]]
    set_mock_value(pmac_x.cs_port, "CS1")
    set_mock_value(pmac_x.cs_number, 1)
    set_mock_value(pmac_x.cs_axis_letter, "X")
    set_mock_value(pmac_y.cs_port, "CS1")
    set_mock_value(pmac_y.cs_number, 1)
    set_mock_value(pmac_y.cs_axis_letter, "Y")
    set_mock_value(sim_x_motor.acceleration_time, 0.5)
    set_mock_value(sim_x_motor.velocity, 1)
    set_mock_value(sim_x_motor.max_velocity, 5)
    set_mock_value(sim_y_motor.acceleration_time, 0.5)
    set_mock_value(sim_y_motor.velocity, 1)
    set_mock_value(sim_y_motor.max_velocity, 10)
    return (sim_pmac, sim_x_motor, sim_y_motor)


async def generate():
    _, sim_x_motor, sim_y_motor = await sim_motors()
    motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 6, sim_y_motor: 7},
        {sim_x_motor: 10, sim_y_motor: 10},
        {sim_x_motor: 5, sim_y_motor: 5},
    )
    # spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 9))
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 11, 20) * ~Line(sim_x_motor, 1, 5, 10)))
    # spec = Fly(1.0 @ Spiral(sim_x_motor, sim_y_motor, 0, 0, 5, 5, 100))
    slice = Path(spec.calculate()).consume()
    ramp_up_pos, _ = calculate_ramp_position_and_duration(slice, motor_info, True)
    ramp_down_pos, _ = calculate_ramp_position_and_duration(slice, motor_info, False)
    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=2)

    motors = spec.axes()
    num_axes = len(motors)

    ruckig = Ruckig(num_axes, 0.01, len(trajectory))
    input = InputParameter(num_axes)
    output = OutputParameter(num_axes, len(trajectory))

    input.current_position = [ramp_up_pos[motor] for motor in motors]
    input.current_velocity = [0] * len(motors)
    input.current_acceleration = [0] * len(motors)

    input.max_velocity = [motor_info.motor_max_velocity[motor] for motor in motors]
    input.max_jerk = [1] * len(motors)
    input.max_acceleration = [1] * len(motors)

    stacked = np.stack([trajectory.positions[m] for m in motors])

    input.intermediate_positions = stacked.T.tolist()

    input.target_position = [ramp_down_pos[motor] for motor in motors]
    input.current_velocity = [0] * len(motors)
    input.current_acceleration = [0] * len(motors)

    first_output, out_list = None, []
    position, position_2 = [], []
    res = Result.Working
    while res == Result.Working:
        res = ruckig.update(input, output)

        position.append(output.new_position[0])
        position_2.append(output.new_position[1])

        out_list.append(copy(output))

        output.pass_to_input(input)

        if not first_output:
            first_output = copy(output)

    plt.plot(position_2, position)
    plt.show()


if __name__ == "__main__":
    asyncio.run(generate())
