import pytest
from scanspec.specs import Fly, Line

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacIO,
)
from ophyd_async.epics.pmac._pmac_trajectory import (
    PmacTrajectoryTriggerLogic,  # noqa: PLC2701
    PmacTriggerLogic,  # noqa: PLC2701
)
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
    set_mock_value(sim_x_motor.max_velocity, 5)
    set_mock_value(sim_y_motor.acceleration_time, 0.5)
    set_mock_value(sim_y_motor.max_velocity, 10)

    yield (sim_pmac, sim_x_motor, sim_y_motor)


async def test_pmac_prepare(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 2))
    trigger_logic = PmacTriggerLogic(spec=spec)
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    await pmac_trajectory.prepare(trigger_logic)

    assert await pmacIO.coord[1].cs_axis_setpoint[7].get_value() == -1.2
    assert await pmacIO.trajectory.positions[7].get_value() == pytest.approx(
        [-1.0, 1, 3, 5, 7, 7.2]
    )
    assert pmac_trajectory.scantime == 4400000
