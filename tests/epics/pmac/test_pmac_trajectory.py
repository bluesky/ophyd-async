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
    set_mock_value(sim_x_motor.velocity, 1)
    set_mock_value(sim_x_motor.max_velocity, 5)
    set_mock_value(sim_y_motor.acceleration_time, 0.5)
    set_mock_value(sim_y_motor.velocity, 1)
    set_mock_value(sim_y_motor.max_velocity, 10)

    yield (sim_pmac, sim_x_motor, sim_y_motor)


async def test_pmac_prepare(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ Line(sim_x_motor, 1, 5, 9))
    trigger_logic = PmacTriggerLogic(spec=spec)
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    await pmac_trajectory.prepare(trigger_logic)

    assert await sim_x_motor.user_setpoint.get_value() == 0.7375
    assert pmac_trajectory.scantime == 9100000

    assert await pmacIO.trajectory.positions[7].get_value() == pytest.approx(
        [
            0.75,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.25,
            2.5,
            2.75,
            3.0,
            3.25,
            3.5,
            3.75,
            4.0,
            4.25,
            4.5,
            4.75,
            5.0,
            5.25,
            5.2625,
        ]
    )
    assert await pmacIO.trajectory.velocities[7].get_value() == pytest.approx(
        [
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.0,
        ]
    )

    assert await pmacIO.trajectory.time_array.get_value() == pytest.approx(
        [
            50000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            50000,
        ]
    )

    assert await pmacIO.trajectory.user_array.get_value() == pytest.approx(
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            8,
        ]
    )
