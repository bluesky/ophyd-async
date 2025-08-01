import pytest
from scanspec.core import Path
from scanspec.specs import Fly, Line, Spiral

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacIO,
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,  # noqa: PLC2701
    _Trajectory,  # noqa: PLC2701
    calculate_ramp_position_and_duration,  # noqa: PLC2701
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
            coord_nums=[],
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
    set_mock_value(sim_x_motor.max_velocity, 5)
    set_mock_value(sim_y_motor.acceleration_time, 0.5)
    set_mock_value(sim_y_motor.max_velocity, 10)

    yield (sim_pmac, sim_x_motor, sim_y_motor)


async def test_line_trajectory_from_slice(sim_motors: tuple[PmacIO, Motor, Motor]):
    _, sim_x_motor, _ = sim_motors
    spec = Fly(2.0 @ Line(sim_x_motor, 1, 5, 9))
    slice = Path(spec.calculate()).consume()

    trajectory = _Trajectory.from_slice(slice, 2)

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


async def test_spiral_trajectory_from_slice(sim_motors: tuple[PmacIO, Motor, Motor]):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Spiral(sim_x_motor, sim_y_motor, 0, 0, 5, 5, 3)
    slice = Path(Fly(2.0 @ spec).calculate()).consume()

    trajectory = _Trajectory.from_slice(slice, 2)
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


async def test_trajectory_from_slice_raises_runtime_error_if_gap(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    _, sim_x_motor, sim_y_motor = sim_motors
    spec = Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)
    slice = Path(Fly(2.0 @ spec).calculate()).consume()

    with pytest.raises(RuntimeError, match="Slice has gaps"):
        _Trajectory.from_slice(slice, 2)


async def test_calculate_ramp_position_and_duration(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    spec = Fly(1.0 @ (Line(sim_y_motor, 10, 12, 3) * ~Line(sim_x_motor, 1, 5, 5)))
    slice = Path(spec.calculate()).consume()

    motor_info = await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])

    ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
        slice, motor_info, True
    )
    ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
        slice, motor_info, False
    )

    assert ramp_up_pos[sim_x_motor] == 0.45
    assert ramp_up_pos[sim_y_motor] == 10
    assert ramp_up_time == 0.1
    assert ramp_down_pos[sim_x_motor] == 5.55
    assert ramp_down_pos[sim_y_motor] == 12
    assert ramp_down_time == 0.1


async def test_motor_info_from_motors(sim_motors: tuple[PmacIO, Motor, Motor]):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    motor_info = await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])
    assert motor_info.cs_port == "CS1"
    assert motor_info.cs_number == 1
    assert motor_info.motor_acceleration_rate == {sim_x_motor: 10, sim_y_motor: 20}
    assert motor_info.motor_cs_index == {sim_x_motor: 6, sim_y_motor: 7}


async def test_multiple_cs_port_raises_runtime_error(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    set_mock_value(
        sim_pmac.assignment[sim_pmac.motor_assignment_index[sim_x_motor]].cs_port, "CS2"
    )

    with pytest.raises(RuntimeError, match="multiple CS ports"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])


async def test_multiple_cs_number_raises_runtime_error(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    set_mock_value(
        sim_pmac.assignment[sim_pmac.motor_assignment_index[sim_x_motor]].cs_number, 2
    )

    with pytest.raises(RuntimeError, match="multiple CS numbers"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])


async def test_duplicate_cs_axis_letter_raises_runtime_error(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    set_mock_value(
        sim_pmac.assignment[
            sim_pmac.motor_assignment_index[sim_x_motor]
        ].cs_axis_letter,
        "Y",
    )

    with pytest.raises(RuntimeError, match="same CS Axis"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])


async def test_unexpected_cs_axis_letter_raises_value_error(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    set_mock_value(
        sim_pmac.assignment[
            sim_pmac.motor_assignment_index[sim_x_motor]
        ].cs_axis_letter,
        "I",
    )

    with pytest.raises(ValueError, match="Failed to get motor CS index"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])


async def test_blank_cs_axis_letter_raises_value_error(
    sim_motors: tuple[PmacIO, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    set_mock_value(
        sim_pmac.assignment[
            sim_pmac.motor_assignment_index[sim_x_motor]
        ].cs_axis_letter,
        "",
    )

    with pytest.raises(ValueError, match="Failed to get motor CS index"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])
