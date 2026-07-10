from unittest.mock import AsyncMock, call, patch

import numpy as np
import pytest
from scanspec.specs import Fly, Line

from ophyd_async.core import (
    get_mock,
    get_mock_execute,
    set_and_wait_for_value,
    set_mock_value,
)
from ophyd_async.epics.motor import Motor

# PmacScanInfo/PmacTrajectoryTriggerLogic are already public - use the
# public path rather than the private module they happen to be defined in.
from ophyd_async.epics.pmac import PmacIO, PmacScanInfo, PmacTrajectoryTriggerLogic

# PmacExecuteState (a status enum PmacTrajectoryTriggerLogic compares
# against internally) and _PmacMotorInfo (an internal dataclass of
# computed per-motor accel/resolution numbers, built via its own
# from_motors() classmethod - not something a caller constructs) are both
# genuinely internal to trajectory generation, not part of the public
# get/set/prepare surface PmacTrajectoryTriggerLogic exposes - checked,
# nothing here looks missing from the public interface.
from ophyd_async.epics.pmac._pmac_trajectory import PmacExecuteState  # noqa: PLC2701
from ophyd_async.epics.pmac._utils import _PmacMotorInfo  # noqa: PLC2701


async def test_pmac_prepare(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 2))
    value = PmacScanInfo(spec=spec, ramp_time=None, turnaround_time=None)
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    await pmac_trajectory.prepare(value)

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


async def test_pmac_prepare_with_configured_ramp(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmac_io, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 2))
    value = PmacScanInfo(spec=spec, ramp_time=2, turnaround_time=None)
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    await pmac_trajectory.prepare(value)

    assert await pmac_io.coord[1].cs_axis_setpoint[7].get_value() == -3.0

    assert await pmac_io.trajectory.positions[7].get_value() == pytest.approx(
        [-1.0, 1.0, 3.0, 5.0, 7.0, 7.2]
    )

    assert await pmac_io.trajectory.velocities[7].get_value() == pytest.approx(
        [2.0, 2.0, 2.0, 2.0, 2.0, 0]
    )

    assert await pmac_io.trajectory.time_array.get_value() == pytest.approx(
        [2000000, 1000000, 1000000, 1000000, 1000000, 200000]
    )

    assert await pmac_io.trajectory.points_to_build.get_value() == 6


async def test_pmac_prepare_with_configured_ramp_and_turnaround(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmac_io, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ (2 * ~Line(sim_x_motor, 1, 5, 2)))
    value = PmacScanInfo(spec=spec, ramp_time=2, turnaround_time=3)
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    await pmac_trajectory.prepare(value)

    assert await pmac_io.coord[1].cs_axis_setpoint[7].get_value() == -3.0

    assert await pmac_io.trajectory.positions[7].get_value() == pytest.approx(
        [
            -1.0,
            1.0,
            3.0,
            5.0,
            7.0,
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

    assert await pmac_io.trajectory.velocities[7].get_value() == pytest.approx(
        [
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
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

    assert await pmac_io.trajectory.time_array.get_value() == pytest.approx(
        [
            2000000,
            1000000,
            1000000,
            1000000,
            1000000,
            200000,
            2600000,
            200000,
            1000000,
            1000000,
            1000000,
            1000000,
            200000,
        ]
    )

    assert await pmac_io.trajectory.points_to_build.get_value() == 13


@pytest.mark.parametrize(
    "x_pos, y_pos, expected_timeout",
    [
        # No cruise, just acceleration
        (1.25, 1, 10.712),
        # Intermediate cruise
        (-10, -5, 12.004),
    ],
)
async def test_pmac_move_to_start(
    x_pos, y_pos, expected_timeout, sim_motors: tuple[PmacIO, Motor, Motor]
):
    pmac_io, sim_x_motor, sim_y_motor = sim_motors
    motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 7, sim_y_motor: 8},
        {sim_x_motor: 10, sim_y_motor: 20},
        {sim_x_motor: 10, sim_y_motor: 10},
        {sim_x_motor: -20, sim_y_motor: -20},
        {sim_x_motor: 20, sim_y_motor: 20},
    )
    coord = pmac_io.coord[motor_info.cs_number]
    ramp_up_position = {sim_x_motor: np.float64(x_pos), sim_y_motor: np.float64(y_pos)}
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)

    # Wrap set_and_wait_for_value to check passed arguments
    with patch(
        "ophyd_async.epics.pmac._pmac_trajectory.set_and_wait_for_value",
        wraps=set_and_wait_for_value,
    ) as spy_set_and_wait_for_value:
        await pmac_trajectory._move_to_start(motor_info, ramp_up_position)

        coord_mock_calls = get_mock(coord).mock_calls

        assert coord_mock_calls[0] == call.defer_moves.put(True)
        assert coord_mock_calls[1] == (
            "cs_axis_setpoint.7.put",
            (np.float64(x_pos)),
            {},
        )
        assert coord_mock_calls[2] == (
            "cs_axis_setpoint.8.put",
            (np.float64(y_pos)),
            {},
        )
        assert coord_mock_calls[3] == call.defer_moves.put(False)

        # All motors should have the same move timeout
        assert all(
            call_.kwargs["set_timeout"] == expected_timeout
            for call_ in spy_set_and_wait_for_value.mock_calls
        )


async def test_pmac_trajectory_kickoff(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmac_io, sim_x_motor, sim_y_motor = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    spec = Fly(2.0 @ (Line(sim_y_motor, 1, 5, 2) * ~Line(sim_x_motor, 1, 5, 2)))
    value = PmacScanInfo(spec=spec, ramp_time=None, turnaround_time=None)
    with patch("ophyd_async.epics.pmac._pmac_trajectory.SLICE_SIZE", 2):
        # This will prepare the buffer with 2 frames of info
        await pmac_trajectory.prepare(value)
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


async def test_pmac_trajectory_stage(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    mock_pmac_trajectory_io = get_mock(pmac_trajectory.pmac_ref().trajectory)
    await pmac_trajectory.stage()

    # Check that all axes are then set not be used
    assert all(
        get_mock(axis).put.assert_called_once_with(False) is None
        for axis in pmac_trajectory.pmac_ref().trajectory.use_axis.values()
    )

    # Check that an empty trajectory is then executed
    assert mock_pmac_trajectory_io.mock_calls[
        len(pmac_trajectory.pmac_ref().trajectory.use_axis) :
    ] == [
        call.time_array.put(np.array(0)),
        call.user_array.put(np.array(8)),
        call.points_to_build.put(1),
        call.build_profile.execute(),
        call.execute_profile.put(True),
    ]


async def test_pmac_trajectory_unstage(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    pmac_trajectory._stop_if_running = AsyncMock()
    await pmac_trajectory.unstage()
    pmac_trajectory._stop_if_running.assert_called_once()


async def test_trajectory_stop_if_running(sim_motors: tuple[PmacIO, Motor, Motor]):
    pmac_io, _, _ = sim_motors
    pmac_trajectory = PmacTrajectoryTriggerLogic(pmac_io)
    execute_mock = get_mock_execute(pmac_io.trajectory.abort_profile)

    # Method not called as no running trajectory
    await pmac_trajectory._stop_if_running()
    execute_mock.assert_not_awaited()

    # Mocking that trajectory is executing
    set_mock_value(
        pmac_trajectory.pmac_ref().trajectory.execute_state, PmacExecuteState.EXECUTING
    )

    # Method called as there is now a running trajectory
    await pmac_trajectory._stop_if_running()
    execute_mock.assert_awaited_once_with()
