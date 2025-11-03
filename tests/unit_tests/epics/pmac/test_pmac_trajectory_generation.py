import numpy as np
import pytest
from scanspec.core import Path
from scanspec.specs import Fly, Line, Spiral

from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacIO,
)
from ophyd_async.epics.pmac._pmac_trajectory_generation import (
    MIN_INTERVAL,  # noqa: PLC2701
    PVT,  # noqa: PLC2701
    Trajectory,  # noqa: PLC2701
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,  # noqa: PLC2701
)
from ophyd_async.testing import set_mock_value


@pytest.fixture
async def motor_info(sim_motors: tuple[PmacIO, Motor, Motor]):
    _, sim_x_motor, sim_y_motor = sim_motors
    yield _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 6, sim_y_motor: 7},
        {sim_x_motor: 10, sim_y_motor: 10},
        {sim_x_motor: 5, sim_y_motor: 5},
    )


async def test_line_trajectory_from_slice(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 9))
    slice = Path(spec.calculate()).consume()
    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=2)
    trajectory = trajectory.with_ramp_down(exit_pvt, {sim_x_motor: np.float64(6)}, 2, 0)

    assert trajectory.positions[sim_x_motor] == pytest.approx(
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
            6.0,
        ]
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
        [
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.25,
            0.0,
        ]
    )

    assert (
        trajectory.user_programs
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
            1,
            8,
        ]
    ).all()

    assert trajectory.durations == pytest.approx(
        [
            2.0,
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
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            2.0,
        ],
    )


async def test_spiral_trajectory_from_slice(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Spiral(sim_x_motor, sim_y_motor, 0, 0, 5, 5, 3)
    slice = Path(Fly(2.0 @ spec).calculate()).consume()

    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=2.0)
    trajectory = trajectory.with_ramp_down(
        exit_pvt, {sim_x_motor: np.float64(0), sim_y_motor: np.float64(0)}, 2.0, 0
    )

    assert trajectory.positions == {
        sim_x_motor: pytest.approx(
            [
                0.0,
                0.60538,
                -0.56648101,
                -1.64763742,
                -1.94954837,
                -1.43181015,
                -0.35683972,
                0.0,
            ]
        ),
        sim_y_motor: pytest.approx(
            [
                0.0,
                -0.82169442,
                -1.32756642,
                -0.64053956,
                0.60491969,
                1.77714744,
                2.47440203,
                0.0,
            ]
        ),
    }

    assert trajectory.velocities == {
        sim_x_motor: pytest.approx(
            [
                0.60538,
                -0.28324051,
                -1.12650871,
                -0.69153368,
                0.10791364,
                0.79635432,
                1.07497043,
                0.0,
            ],
        ),
        sim_y_motor: pytest.approx(
            [
                -0.82169442,
                -0.66378321,
                0.09057743,
                0.96624305,
                1.2088435,
                0.93474117,
                0.69725459,
                0.0,
            ],
        ),
    }

    assert trajectory.durations == pytest.approx(
        [2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0]
    )

    assert (trajectory.user_programs == [1, 1, 1, 1, 1, 1, 1, 8]).all()


async def test_snaked_trajectory_with_gaps(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)))
    slice = Path(spec.calculate()).consume()

    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=1.0)
    trajectory = trajectory.with_ramp_down(
        exit_pvt, {sim_x_motor: np.float64(6.0), sim_y_motor: np.float64(12)}, 1.0, 0
    )

    assert trajectory.positions[sim_x_motor] == pytest.approx(
        [
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
            6.0,
        ]
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
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

    assert trajectory.positions[sim_y_motor] == pytest.approx(
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
        ],
        1e-3,
    )

    assert trajectory.velocities[sim_y_motor] == pytest.approx(
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
            0.0,
            0.976,
            3.125,
            0.976,
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
            0.977,
            3.125,
            0.977,
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
        ],
        1e-3,
    )

    assert (
        trajectory.user_programs
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
    ).all()

    assert trajectory.durations == pytest.approx(
        [
            1.0,
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
            0.1,
            0.22,
            0.22,
            0.1,
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
            0.1,
            0.22,
            0.22,
            0.1,
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
            1.0,
        ],
        1e-5,
    )


async def test_grid_trajectory_with_gaps(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 12, 3) * Line(sim_x_motor, 1, 5, 5)))
    slice = Path(spec.calculate()).consume()

    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=1.0)
    trajectory = trajectory.with_ramp_down(
        exit_pvt,
        {sim_x_motor: np.float64(6.0), sim_y_motor: np.float64(12.0)},
        1.0,
        0.0,
    )

    assert trajectory.positions[sim_x_motor] == pytest.approx(
        [
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
            5.5421,
            4.3053,
            1.6947,
            0.4572,
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
            5.5421,
            4.3053,
            1.6947,
            0.4572,
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
            6,
        ],
        1e-3,
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
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
            1.0,
            0.3818,
            -4.9822,
            -4.9822,
            0.3818,
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
            0.3818,
            -4.9822,
            -4.9822,
            0.3818,
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
        ],
        1e-3,
    )

    assert trajectory.positions[sim_y_motor] == pytest.approx(
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
            10.0,
            10.01865,
            10.34235,
            10.65764,
            10.98134,
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
            11.01865,
            11.34235,
            11.65764,
            11.98134,
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

    assert trajectory.velocities[sim_y_motor] == pytest.approx(
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
            0.0,
            0.601684717208,
            0.601684717208,
            0.601684717208,
            0.601684717208,
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
            0.601684717208,
            0.601684717208,
            0.601684717208,
            0.601684717208,
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

    assert (
        trajectory.user_programs
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
            2,
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
    ).all()

    assert trajectory.durations == pytest.approx(
        [
            1.0,
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
            0.062,
            0.538,
            0.524,
            0.538,
            0.062,
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
            0.062,
            0.538,
            0.524,
            0.538,
            0.062,
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
            1.0,
        ],
        1e-5,
    )


async def test_from_gap(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)))
    slice = Path(spec.calculate()).consume()

    # This is info about the frame just before a gap is created.
    entry_pvt = PVT(
        position={sim_x_motor: np.float64(5.5), sim_y_motor: np.float64(10.0)},
        velocity={sim_x_motor: np.float64(1.0), sim_y_motor: np.float64(0.0)},
        time=np.float64(1),
    )

    trajectory, _ = Trajectory.from_gap(
        motor_info, 5, [sim_x_motor, sim_y_motor], slice, entry_pvt
    )

    assert trajectory.positions[sim_x_motor] == pytest.approx(
        [
            5.5,
            5.55,
            5.55,
            5.55,
            5.5,
            5.0,
        ],
    )

    assert trajectory.positions[sim_y_motor] == pytest.approx(
        [
            10.0,
            10.05,
            10.5,
            10.95,
            11.0,
            11.0,
        ],
        1e-3,
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
        [
            1.0,
            -0.0,
            0.0,
            -0.0,
            -1.0,
            -1.0,
        ],
    )

    assert trajectory.velocities[sim_y_motor] == pytest.approx(
        [
            0.0,
            0.9765,
            3.125,
            0.9765,
            0.0,
            0.0,
        ],
        1e-3,
    )

    assert trajectory.durations == pytest.approx(
        [
            1.0,
            0.1,
            0.22,
            0.22,
            0.1,
            0.5,
        ]
    )

    assert (trajectory.user_programs == [1, 2, 2, 2, 1, 1]).all()


async def test_from_collection_window(sim_motors: tuple[PmacIO, Motor, Motor]):
    _, _, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 1, 5, 5)))
    path = Path(spec.calculate())
    slice = path.consume()

    entry_pvt = PVT(
        position={sim_y_motor: np.float64(1.0)},
        velocity={sim_y_motor: np.float64(0.5)},
        time=np.float64(0.5),
    )

    trajectory, _ = Trajectory.from_collection_window(
        1, 5, [sim_y_motor], slice, entry_pvt
    )

    assert trajectory.positions[sim_y_motor] == pytest.approx(
        [1.5, 2, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    )

    assert trajectory.velocities[sim_y_motor] == pytest.approx(
        [0.75, 1, 1, 1, 1, 1, 1, 1],
    )

    assert trajectory.durations == pytest.approx(
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    )

    assert (trajectory.user_programs == [1, 1, 1, 1, 1, 1, 1, 1]).all()


async def test_appending_trajectory(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 11, 2) * ~Line(sim_x_motor, 1, 3, 3)))
    path = Path(spec.calculate())
    slice = path.consume(3)

    first_trajectory, first_exit_pvt = Trajectory.from_slice(
        slice, motor_info, ramp_up_time=1
    )

    slice = path.consume()
    second_trajectory, second_exit_pvt = Trajectory.from_slice(
        slice, motor_info, first_exit_pvt
    )

    overall_trajectory = Trajectory.from_trajectories(
        [first_trajectory, second_trajectory], [sim_x_motor, sim_y_motor]
    )

    overall_trajectory = overall_trajectory.with_ramp_down(
        second_exit_pvt,
        {sim_x_motor: np.float64(0), sim_y_motor: np.float64(11.0)},
        1.0,
        0.0,
    )

    assert overall_trajectory.positions[sim_x_motor] == pytest.approx(
        [
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            3.55,
            3.55,
            3.55,
            3.5,
            3.0,
            2.5,
            2.0,
            1.5,
            1.0,
            0.5,
            0.0,
        ]
    )

    assert overall_trajectory.positions[sim_y_motor] == pytest.approx(
        [
            10,
            10,
            10,
            10,
            10,
            10,
            10,
            10.05,
            10.50,
            10.95,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
            11.0,
        ],
        1e-3,
    )

    assert overall_trajectory.velocities[sim_x_motor] == pytest.approx(
        [
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
            0.0,
        ]
    )

    assert overall_trajectory.velocities[sim_y_motor] == pytest.approx(
        [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.9765,
            3.125,
            0.9765,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        1e-3,
    )

    assert overall_trajectory.durations == pytest.approx(
        [
            1.0,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.1,
            0.22,
            0.22,
            0.1,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            1.0,
        ],
        1e-5,
    )

    assert (
        overall_trajectory.user_programs
        == [
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
            8,
        ]
    ).all()


async def test_hardware_triggered_step_scan(
    sim_motors: tuple[PmacIO, Motor, Motor], motor_info: _PmacMotorInfo
):
    _, sim_x_motor, _ = sim_motors
    spec = 1.0 @ Line(sim_x_motor, 1, 3, 3)
    path = Path(spec.calculate())
    slice = path.consume()

    trajectory, exit_pvt = Trajectory.from_slice(slice, motor_info, ramp_up_time=2)
    trajectory = trajectory.with_ramp_down(exit_pvt, {sim_x_motor: np.float64(6)}, 2, 0)

    assert trajectory.positions[sim_x_motor] == pytest.approx(
        [
            1.0,
            1.0,
            1.0,
            1.5,
            2.0,
            2.0,
            2.0,
            2.5,
            3.0,
            3.0,
            3.0,
            6.0,
        ]
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
        [
            0.0,
            0.0,
            0.0,
            3.125,
            0.0,
            0.0,
            0.0,
            3.125,
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        1e-5,
    )

    assert trajectory.durations == pytest.approx(
        [
            2.0,
            0.5,
            0.5,
            0.32,
            0.32,
            0.5,
            0.5,
            0.32,
            0.32,
            0.5,
            0.5,
            2.0,
        ],
        1e-5,
    )

    assert (
        trajectory.user_programs
        == [
            1,
            1,
            1,
            2,
            1,
            1,
            1,
            2,
            1,
            1,
            1,
            8,
        ]
    ).all()


async def test_small_turnaround_durations_are_quantized(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    pmac, sim_x_motor, sim_y_motor = sim_motors

    # These parameters result in gap point durations < MIN_INTERVAL
    set_mock_value(sim_y_motor.max_velocity, 100)
    set_mock_value(sim_y_motor.acceleration_time, 0.25)
    motor_info = await _PmacMotorInfo.from_motors(pmac, [sim_x_motor, sim_y_motor])
    spec = Fly(float(1) @ (Line(sim_y_motor, 0, 1, 10) * ~Line(sim_x_motor, 0, 1, 10)))
    slice = Path(spec.calculate()).consume()

    # Parse the first turnaround profile
    trajectory, _ = Trajectory.from_gap(
        motor_info=motor_info,
        gap=10,
        motors=[sim_x_motor, sim_y_motor],
        slice=slice,
        entry_pvt=PVT(
            position={sim_x_motor: np.float64(1.055), sim_y_motor: np.float64(0)},
            velocity={sim_x_motor: np.float64(0.1111), sim_y_motor: np.float64(0)},
            time=np.float64(0.5),
        ),
    )

    # Check that gap durations are snapped up to nearest interval
    assert min(trajectory.durations) == pytest.approx(MIN_INTERVAL)
