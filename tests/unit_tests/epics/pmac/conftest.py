import pytest

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.testing import set_mock_value


@pytest.fixture
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
    yield (sim_pmac, sim_x_motor, sim_y_motor)
