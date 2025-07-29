import pytest
from scanspec.core import Path
from scanspec.specs import Line, fly

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


async def test_trajectory_from_slice(sim_x_motor):
    spec = fly(Line(sim_x_motor, 1, 5, 9), 1)
    slice = Path(spec.calculate()).consume()

    trajectory = Trajectory.from_slice(slice, 0.05, True)

    assert trajectory.positions[sim_x_motor] == pytest.approx(
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
        ]
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
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
        ]
    )

    assert trajectory.velocities[sim_x_motor] == pytest.approx(
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


async def test_trajectory_from_slice_raises_runtime_error_if_gap(
    sim_y_motor, sim_x_motor
):
    spec = fly(Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5), 1)
    slice = Path(spec.calculate()).consume()

    with pytest.raises(RuntimeError, match="Slice has gaps"):
        Trajectory.from_slice(slice, 0.05, True)
