import pytest
from scanspec.regions import Circle
from scanspec.specs import Line, fly

from ophyd_async.core import DeviceCollector, set_mock_value
from ophyd_async.epics.pmac import PmacCSMotor, PmacTrajectory


@pytest.fixture
async def sim_x_motor():
    async with DeviceCollector(mock=True):
        sim_motor = PmacCSMotor("BLxxI-MO-TABLE-01:X", "1", "x", name="sim_x_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.velocity, 1)
    set_mock_value(sim_motor.acceleration_time, 1)
    yield sim_motor


@pytest.fixture
async def sim_y_motor():
    async with DeviceCollector(mock=True):
        sim_motor = PmacCSMotor("BLxxI-MO-TABLE-01:Y", "1", "y", name="sim_y_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.velocity, 1)
    set_mock_value(sim_motor.acceleration_time, 1)
    yield sim_motor


async def test_sim_pmac_trajectory(sim_x_motor, sim_y_motor) -> None:
    # Test the generated Trajectory profile from a scanspec
    async with DeviceCollector(mock=True):
        prefix = "BLxxI-MO-STEP-01"
        motors = [sim_x_motor, sim_y_motor]
        traj = PmacTrajectory(prefix, 2, motors, name="sim_pmac")
        grid = Line("y", 10, 20, 11) * ~Line("x", 1, 5, 5)
        spec = fly(grid, 0.4) & Circle("x", "y", 3.0, 15, radius=3)
        stack = spec.calculate()
        await traj.prepare(stack)
    assert traj.profile == {
        "duration": [
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
            0.4,
        ],
        "x": [
            3,
            5,
            4,
            3,
            2,
            1,
            1,
            2,
            3,
            4,
            5,
            5,
            4,
            3,
            2,
            1,
            1,
            2,
            3,
            4,
            5,
            5,
            4,
            3,
            2,
            1,
            3,
        ],
        "x_velocity": [
            5.0,
            -2.5,
            -2.5,
            -2.5,
            -2.5,
            0.0,
            2.5,
            2.5,
            2.5,
            2.5,
            0.0,
            -2.5,
            -2.5,
            -2.5,
            -2.5,
            0.0,
            2.5,
            2.5,
            2.5,
            2.5,
            0.0,
            -2.5,
            -2.5,
            -2.5,
            -2.5,
            5.0,
            0,
        ],
        "y": [
            12,
            13,
            13,
            13,
            13,
            13,
            14,
            14,
            14,
            14,
            14,
            15,
            15,
            15,
            15,
            15,
            16,
            16,
            16,
            16,
            16,
            17,
            17,
            17,
            17,
            17,
            18,
        ],
        "y_velocity": [
            2.5,
            0.0,
            0.0,
            0.0,
            0.0,
            2.5,
            0.0,
            0.0,
            0.0,
            0.0,
            2.5,
            0.0,
            0.0,
            0.0,
            0.0,
            2.5,
            0.0,
            0.0,
            0.0,
            0.0,
            2.5,
            0.0,
            0.0,
            0.0,
            0.0,
            2.5,
            0,
        ],
    }

    assert traj.initial_pos["x"] == 0.5
    assert traj.initial_pos["y"] == 10.75
