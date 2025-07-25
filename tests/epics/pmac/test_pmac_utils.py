import pytest
from scanspec.core import Path
from scanspec.specs import Line, fly

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacMotorInfo,
    calculate_ramp_position_and_duration,
)


@pytest.fixture
async def sim_x_motor():
    async with init_devices(mock=True):
        sim_motor = Motor("TEST")
    yield sim_motor


async def test_calculate_ramp(sim_x_motor):
    spec = fly(Line(sim_x_motor, 1, 5, 9), 1)
    slice = Path(spec.calculate()).consume()
    motor_info = PmacMotorInfo(
        cs_port="CS3",
        cs_number=3,
        motor_cs_index={sim_x_motor: 9},
        motor_acceleration_rate={sim_x_motor: 10},
    )
    calculate_ramp_position_and_duration(slice, motor_info, True)
