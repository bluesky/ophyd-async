import pytest
from scanspec.core import Path
from scanspec.specs import Fly, Line, Spiral

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac._utils import (
    Trajectory,  # noqa: PLC2701
)


@pytest.fixture
async def sim_x_motor():
    async with init_devices(mock=True):
        sim_motor = Motor("X")
    yield sim_motor


@pytest.fixture
async def sim_y_motor():
    async with init_devices(mock=True):
        sim_motor = Motor("Y")
    yield sim_motor


async def test_trajectory_from_slice(sim_x_motor: Motor):
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 9))
    slice = Path(spec.calculate()).consume()

    trajectory = Trajectory.from_slice(slice, 2)

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
            8,
        ]
    ).all()

    assert (
        trajectory.durations
        == [
            2000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
            1000000.0,
        ]
    ).all()


async def test_trajectory_from_slice_raises_runtime_error_if_gap(
    sim_y_motor, sim_x_motor
):
    spec = Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)
    slice = Path(Fly(2.0 @ spec).calculate()).consume()

    with pytest.raises(RuntimeError, match="Slice has gaps"):
        Trajectory.from_slice(slice, 2)


async def test_spiral(sim_y_motor, sim_x_motor):
    spec = Spiral(sim_x_motor, sim_y_motor, 0, 0, 5, 5, 3)
    slice = Path(Fly(2.0 @ spec).calculate()).consume()

    trajectory = Trajectory.from_slice(slice, 2)
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
            ]
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
            ]
        ),
    }

    assert trajectory.durations == pytest.approx(
        [2000000.0, 1000000.0, 1000000.0, 1000000.0, 1000000.0, 1000000.0, 1000000.0]
    )

    assert trajectory.user_programs == pytest.approx([1, 1, 1, 1, 1, 1, 8])
