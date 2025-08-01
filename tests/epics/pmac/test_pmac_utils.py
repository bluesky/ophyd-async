import pytest
from scanspec.core import Path
from scanspec.specs import Fly, Line

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacMotorInfo,
)
from ophyd_async.epics.pmac._utils import (
    calculate_ramp_position_and_duration,  # noqa: PLC2701
)


@pytest.fixture
async def sim_x_motor():
    async with init_devices(mock=True):
        sim_motor = Motor("X")
    yield sim_motor


@pytest.fixture
async def sim_y_motor():
    async with init_devices(mock=True):
        sim_motor = Motor("Y")
    yield sim_motor


async def test_calculate_ramp_position_and_duration(sim_x_motor, sim_y_motor):
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)))
    slice = Path(spec.calculate()).consume()

    # TODO: Replace with PmacMotorInfo.from_motors() https://github.com/bluesky/ophyd-async/issues/954
    motor_info = PmacMotorInfo(
        cs_port="CS3",
        cs_number=3,
        motor_cs_index={sim_x_motor: 8, sim_y_motor: 9},
        motor_acceleration_rate={sim_x_motor: 10, sim_y_motor: 10},
    )

    ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
        slice, motor_info, True
    )
    ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
        slice, motor_info, False
    )

    assert ramp_up_pos[sim_x_motor] == 0.45
    assert ramp_up_pos[sim_y_motor] == 10
    assert ramp_up_time == 0.1
    assert ramp_down_pos[sim_x_motor] == 5.55
    assert ramp_down_pos[sim_y_motor] == 12
    assert ramp_down_time == 0.1
