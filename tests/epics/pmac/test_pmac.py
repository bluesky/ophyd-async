import pytest
from scanspec.specs import Line, fly

from ophyd_async.core import DeviceCollector, set_mock_value
from ophyd_async.epics.motion import Motor
from ophyd_async.epics.pmac import PmacTrajectory


@pytest.fixture
async def sim_x_motor():
    async with DeviceCollector(mock=True):
        sim_motor = Motor("BLxxI-MO-STAGE-01:X", name="sim_x_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.acceleration_time, 0.5)
    set_mock_value(sim_motor.max_velocity, 5)
    set_mock_value(sim_motor.velocity, 0.5)
    set_mock_value(sim_motor.output_link, "@asyn(BRICK1.CS3,9)")

    yield sim_motor


async def test_sim_pmac_simple_trajectory(sim_x_motor) -> None:
    # Test the generated Trajectory profile from a scanspec
    prefix = "BLxxI-MO-STEP-01"
    async with DeviceCollector(mock=True):
        traj = PmacTrajectory(prefix, "BRICK1.CS3", name="sim_pmac")
    spec = fly(Line(sim_x_motor, 1, 5, 9), 1)
    stack = spec.calculate()
    await traj.prepare(stack)
    assert traj.profile == {
        "duration": [
            1050000,
            1000000,
            1000000,
            1000000,
            1000000,
            1000000,
            1000000,
            1000000,
            1000000,
            50000,
        ],
        "Z": [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.0125],
        "Z_velocity": [
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0,
        ],
    }

    assert await traj.points_to_build.get_value() == 10
    assert traj.initial_pos["Z"] == 0.9875
    assert traj.scantime == 9.1

    await traj.kickoff()
