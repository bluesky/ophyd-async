from unittest.mock import call, patch

import numpy as np
import pytest
from scanspec.specs import Fly, Line

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_trajectory import (
    PmacTrajectoryTriggerLogic,  # noqa: PLC2701
)
from ophyd_async.epics.pmac._pmac_trajectory_generation import (
    _Trajectory,  # noqa: PLC2701
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,  # noqa: PLC2701
)
from ophyd_async.testing import (
    get_mock,
    set_mock_value,
)


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
    pmacIO, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 2))
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    await pmac_trajectory.prepare(spec)

    assert await pmacIO.coord[1].cs_axis_setpoint[7].get_value() == -1.2

    assert await pmacIO.trajectory.positions[7].get_value() == pytest.approx(
        [-1.0, 1.0, 3.0, 5.0, 7.0, 7.2]
    )
    assert pmac_trajectory.scantime == pytest.approx(4400000)


async def test_pmac_build_trajectory(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, sim_x_motor, _ = sim_motors
    trajectory = _Trajectory(
        {sim_x_motor: np.array([-1.0, 1.0, 3.0, 5.0, 7.0])},
        {sim_x_motor: np.array([2.0, 2.0, 2.0, 2.0, 2.0])},
        np.array([1, 1, 1, 1, 8], dtype=np.int32),
        np.array([0.2, 1.0, 1.0, 1.0, 1.0], dtype=np.float64),
    )
    motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 6},
        {sim_x_motor: 10},
        {sim_x_motor: 10},
    )

    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    await pmac_trajectory._build_trajectory(trajectory, motor_info)

    assert await pmacIO.trajectory.profile_cs_name.get_value() == "CS1"
    assert pmac_trajectory.scantime == pytest.approx(4200000)
    assert await pmacIO.trajectory.time_array.get_value() == pytest.approx(
        [
            200000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
        ]
    )

    assert (
        await pmacIO.trajectory.positions[7].get_value() == [-1.0, 1, 3, 5, 7.0]
    ).all()

    assert (
        await pmacIO.trajectory.velocities[7].get_value()
        == [
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
        ]
    ).all()
    assert await pmacIO.trajectory.points_to_build.get_value() == 5


async def test_pmac_move_to_start(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, sim_x_motor, sim_y_motor = sim_motors
    motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 6, sim_y_motor: 7},
        {sim_x_motor: 10, sim_y_motor: 20},
        {sim_x_motor: 10, sim_y_motor: 10},
    )
    coord = pmacIO.coord[motor_info.cs_number]
    ramp_up_position = {sim_x_motor: np.float64(-1.2), sim_y_motor: np.float64(-0.6)}
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)

    await pmac_trajectory._move_to_start(motor_info, ramp_up_position)

    coord_mock_calls = get_mock(coord).mock_calls

    assert coord_mock_calls[0] == call.defer_moves.put(True, wait=True)
    assert coord_mock_calls[1] == (
        "cs_axis_setpoint.7.put",
        (np.float64(-1.2)),
        {"wait": True},
    )
    assert coord_mock_calls[2] == (
        "cs_axis_setpoint.8.put",
        (np.float64(-0.6)),
        {"wait": True},
    )
    assert coord_mock_calls[3] == call.defer_moves.put(False, wait=True)


async def test_pmac_trajectory_kickoff(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmacIO, sim_x_motor, sim_y_motor = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    spec = Fly(2.0 @ (Line(sim_y_motor, 1, 5, 2) * ~Line(sim_x_motor, 1, 5, 2)))
    with patch("ophyd_async.epics.pmac._pmac_trajectory.SLICE_SIZE", 2):
        # This will prepare the buffer with 2 frames of info
        await pmac_trajectory.prepare(spec)
        # This will consume another 2 frames
        set_mock_value(
            pmacIO.total_points, 2
        )  # Only one value in observe_value(total_points)
        await pmac_trajectory.kickoff()  # Executes trajectory, appending once
        await pmac_trajectory.complete()  # Block until trajectory is complete

    sim_y_motor_position_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmacIO.trajectory.positions[7]).mock_calls
    ]

    sim_x_motor_position_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmacIO.trajectory.positions[8]).mock_calls
    ]

    # Appended to buffer once in prepare and once after kickoff
    assert len(sim_x_motor_position_arrays) == len(sim_y_motor_position_arrays) == 2

    assert np.concatenate(sim_y_motor_position_arrays) == pytest.approx(
        [
            -1.0,
            1.0,
            3.0,
            5.0,
            7.0,
            7.2,
            7.2,
            7.2,
            7.0,
            5.0,
            3.0,
            1.0,
            -1,
            -1.2,
        ]
    )
    assert np.concatenate(sim_x_motor_position_arrays) == pytest.approx(
        [
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.4,
            3.0,
            4.6,
            5.0,
            5.0,
            5.0,
            5.0,
            5.0,
            5.0,
        ]
    )


async def test_pmac_trajectory_execute_trajectory_raises_exception_if_no_prepare(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmacIO, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    with pytest.raises(
        RuntimeError, match="Cannot execute trajectory. Must call prepare first."
    ):
        await pmac_trajectory._execute_trajectory()


async def test_pmac_trajectory_complete(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    with pytest.raises(RuntimeError, match="Cannot complete. Must call kickoff first."):
        await pmac_trajectory.complete()


async def test_pmac_trajectory_stop(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmacIO, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmacIO)
    assert await pmac_trajectory.pmac.trajectory.abort_profile.get_value() is not True
    await pmac_trajectory.stop()
    assert await pmac_trajectory.pmac.trajectory.abort_profile.get_value() is True
