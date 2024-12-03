import pytest
from scanspec.specs import Line, fly

from ophyd_async.core import DeviceCollector, set_mock_value
from ophyd_async.epics.pmac import (
    Pmac,
    PmacMotor,
    PmacTrajectoryTriggerLogic,
    PmacTrajInfo,
)


@pytest.fixture
async def sim_x_motor():
    async with DeviceCollector(mock=True):
        sim_motor = PmacMotor("BLxxI-MO-STAGE-01:X", name="sim_x_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.acceleration_time, 0.5)
    set_mock_value(sim_motor.max_velocity, 5)
    set_mock_value(sim_motor.velocity, 0.5)
    set_mock_value(sim_motor.output_link, "@asyn(BRICK1.CS3,9)")

    yield sim_motor


@pytest.fixture
async def sim_y_motor():
    async with DeviceCollector(mock=True):
        sim_motor = PmacMotor("BLxxI-MO-STAGE-01:Y", name="sim_x_motor")

    set_mock_value(sim_motor.motor_egu, "mm")
    set_mock_value(sim_motor.precision, 3)
    set_mock_value(sim_motor.acceleration_time, 0.5)
    set_mock_value(sim_motor.max_velocity, 5)
    set_mock_value(sim_motor.velocity, 0.5)
    set_mock_value(sim_motor.output_link, "@asyn(BRICK1,8)")
    set_mock_value(sim_motor.cs_axis, "Y")
    set_mock_value(sim_motor.cs_port, "BRICK1.CS3")

    yield sim_motor


@pytest.fixture
async def sim_pmac():
    async with DeviceCollector(mock=True):
        sim_pmac = Pmac("BLxxI-MO-STEP-01", name="sim_pmac")
    yield sim_pmac


async def test_sim_pmac_simple_trajectory(sim_x_motor, sim_pmac) -> None:
    # Test the generated Trajectory profile from a scanspec
    spec = fly(Line(sim_x_motor, 1, 5, 9), 1)
    info = PmacTrajInfo(spec=spec)
    trigger_logic = PmacTrajectoryTriggerLogic(sim_pmac)
    await trigger_logic.prepare(info)
    assert await trigger_logic.pmac.positions[9].get_value() == pytest.approx(
        [
            0.75,
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
    assert await trigger_logic.pmac.velocities[9].get_value() == pytest.approx(
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
            0,
        ]
    )
    assert (
        await trigger_logic.pmac.time_array.get_value()
        == [
            50000.0,
            1000000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            500000.0,
            50000.0,
        ]
    ).all()
    assert (
        await trigger_logic.pmac.user_array.get_value()
        == [
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
    ).all()
    assert await trigger_logic.pmac.points_to_build.get_value() == 19
    assert await sim_x_motor.user_setpoint.get_value() == 0.7375
    assert trigger_logic.scantime == 9.1

    await trigger_logic.kickoff()


async def test_sim_grid_trajectory(sim_x_motor, sim_y_motor, sim_pmac) -> None:
    # Test the generated Trajectory profile from a scanspec
    spec = fly(Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5), 1)
    info = PmacTrajInfo(spec=spec)
    trigger_logic = PmacTrajectoryTriggerLogic(sim_pmac)
    await trigger_logic.prepare(info)
    assert await trigger_logic.pmac.positions[9].get_value() == pytest.approx(
        [
            0.5,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
            4.5,
            5.0,
            5.5,
            5.55,
            5.55,
            5.55,
            5.5,
            5.0,
            4.5,
            4.0,
            3.5,
            3.0,
            2.5,
            2.0,
            1.5,
            1.0,
            0.5,
            0.45,
            0.45,
            0.45,
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
            4.5,
            5.0,
            5.5,
            5.55,
        ]
    )
    assert await trigger_logic.pmac.velocities[9].get_value() == pytest.approx(
        [
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            -0.0,
            0.0,
            -0.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -1.0,
            -0.0,
            0.0,
            -0.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            0.0,
        ]
    )
    assert await trigger_logic.pmac.positions[8].get_value() == pytest.approx(
        [
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.0,
            10.05,
            10.5,
            10.95,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.05,
            11.5,
            11.95,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
            12.0,
        ]
    )
    assert await trigger_logic.pmac.velocities[8].get_value() == pytest.approx(
        [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            3.16227766,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            3.16227766,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ]
    )
    assert await trigger_logic.pmac.time_array.get_value() == pytest.approx(
        [
            100000,
            1000000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            500000,
            100000,
            216227,
            216227,
            100000,
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
            100000,
            216227,
            216227,
            100000,
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
            100000,
        ]
    )
    assert await trigger_logic.pmac.user_array.get_value() == pytest.approx(
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
            2,
            2,
            2,
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
            2,
            2,
            2,
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
    assert await trigger_logic.pmac.points_to_build.get_value() == 39
    assert await sim_x_motor.user_setpoint.get_value() == 0.45
    assert trigger_logic.scantime == 15.2

    await trigger_logic.kickoff()
