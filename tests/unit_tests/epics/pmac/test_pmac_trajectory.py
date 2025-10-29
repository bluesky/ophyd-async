from unittest.mock import call, patch

import numpy as np
import pytest
from scanspec.specs import Fly, Line

from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_trajectory import (
    PmacTrajectoryTriggerLogic,  # noqa: PLC2701
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,  # noqa: PLC2701
)
from ophyd_async.testing import (
    get_mock,
    set_mock_value,
)


async def test_pmac_prepare(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 2))
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    await pmac_trajectory.prepare(spec)

    assert await pmac_io.coord[1].cs_axis_setpoint[7].get_value() == -1.2

    assert await pmac_io.trajectory.positions[7].get_value() == pytest.approx(
        [-1.0, 1.0, 3.0, 5.0, 7.0, 7.2]
    )

    assert await pmac_io.trajectory.velocities[7].get_value() == pytest.approx(
        [2.0, 2.0, 2.0, 2.0, 2.0, 0]
    )

    assert await pmac_io.trajectory.time_array.get_value() == pytest.approx(
        [200000, 1000000, 1000000, 1000000, 1000000, 200000]
    )

    assert await pmac_io.trajectory.points_to_build.get_value() == 6


async def test_pmac_move_to_start(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, sim_x_motor, sim_y_motor = sim_motors
    motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 6, sim_y_motor: 7},
        {sim_x_motor: 10, sim_y_motor: 20},
        {sim_x_motor: 10, sim_y_motor: 10},
    )
    coord = pmac_io.coord[motor_info.cs_number]
    ramp_up_position = {sim_x_motor: np.float64(-1.2), sim_y_motor: np.float64(-0.6)}
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)

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
    pmac_io, sim_x_motor, sim_y_motor = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    spec = Fly(2.0 @ (Line(sim_y_motor, 1, 5, 2) * ~Line(sim_x_motor, 1, 5, 2)))
    with patch("ophyd_async.epics.pmac._pmac_trajectory.SLICE_SIZE", 2):
        # This will prepare the buffer with 2 frames of info
        await pmac_trajectory.prepare(spec)
        # This will consume another 2 frames
        set_mock_value(
            pmac_io.trajectory.total_points, 2
        )  # Only one value in observe_value(total_points)
        await pmac_trajectory.kickoff()  # Executes trajectory, appending once
        await pmac_trajectory.complete()  # Block until trajectory is complete

    sim_y_motor_position_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmac_io.trajectory.positions[7]).mock_calls
    ]

    sim_x_motor_position_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmac_io.trajectory.positions[8]).mock_calls
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
            1.395,
            3.0,
            4.605,
            5.0,
            5.0,
            5.0,
            5.0,
            5.0,
            5.0,
        ],
        1e-3,
    )

    sim_y_motor_velocity_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmac_io.trajectory.velocities[7]).mock_calls
    ]

    sim_x_motor_velocity_arrays = [
        np.array(call.args[0])
        for call in get_mock(pmac_io.trajectory.velocities[8]).mock_calls
    ]

    assert np.concatenate(sim_y_motor_velocity_arrays) == pytest.approx(
        [
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
            0.0,
            0.0,
            0.0,
            -2.0,
            -2.0,
            -2.0,
            -2.0,
            -2.0,
            0.0,
        ]
    )
    assert np.concatenate(sim_x_motor_velocity_arrays) == pytest.approx(
        [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            3.951,
            8.888,
            3.951,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        1e-3,
    )


async def test_pmac_trajectory_kickoff_trajectory_raises_exception_if_no_prepare(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    with pytest.raises(RuntimeError, match="Cannot kickoff. Must call prepare first."):
        await pmac_trajectory.kickoff()


async def test_pmac_trajectory_complete(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    with pytest.raises(RuntimeError, match="Cannot complete. Must call kickoff first."):
        await pmac_trajectory.complete()


async def test_pmac_trajectory_stop(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    abort_profile = get_mock(pmac_trajectory.pmac.trajectory.abort_profile)
    await pmac_trajectory.stop()
    abort_profile.put.assert_called_once()
