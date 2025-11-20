import pytest
from scanspec.core import Path
from scanspec.specs import Fly, Line

from ophyd_async.core import set_mock_value
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import (
    PmacIO,
)
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,  # noqa: PLC2701
    calculate_ramp_position_and_duration,  # noqa: PLC2701
)


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


async def test_motor_info_from_cs_motors(sim_cs_motors: tuple[PmacIO, Motor, Motor]):
    pmac, sim_cs_x_motor, sim_cs_y_motor = sim_cs_motors
    motor_info = await _PmacMotorInfo.from_motors(
        pmac, [sim_cs_x_motor, sim_cs_y_motor]
    )
    expected_motor_info = _PmacMotorInfo(
        "CS5",
        5,
        {sim_cs_x_motor: 7, sim_cs_y_motor: 8},
        {sim_cs_x_motor: 10.0, sim_cs_y_motor: 20.0},
        {sim_cs_x_motor: 5.0, sim_cs_y_motor: 10.0},
    )
    assert motor_info == expected_motor_info


async def test_motor_info_from_both_motors(
    sim_both_motors: tuple[PmacIO, Motor, Motor, Motor, Motor],
):
    sim_pmac, sim_x_motor, sim_y_motor, sim_cs_x_motor, sim_cs_y_motor = sim_both_motors

    with pytest.raises(ValueError, match="raw motors and CS motors"):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_cs_y_motor])


async def test_motor_info_from_motors(sim_motors: tuple[PmacIO, Motor, Motor]):
    sim_pmac, sim_x_motor, sim_y_motor = sim_motors
    motor_info = await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])
    expected_motor_info = _PmacMotorInfo(
        "CS1",
        1,
        {sim_x_motor: 7, sim_y_motor: 8},
        {sim_x_motor: 10, sim_y_motor: 20},
        {sim_x_motor: 5, sim_y_motor: 10},
    )
    assert motor_info == expected_motor_info


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

    with pytest.raises(
        ValueError,
        match="Motor sim_y_motor assigned to 'Y' "
        "but another motor is already assigned to this axis.",
    ):
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

    with pytest.raises(
        ValueError,
        match="Motor sim_x_motor assigned to 'I' "
        "but must be assigned to one of 'A,B,C,U,V,W,X,Y,Z'",
    ):
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

    with pytest.raises(
        ValueError,
        match="Motor sim_x_motor does not have an axis assignment.",
    ):
        await _PmacMotorInfo.from_motors(sim_pmac, [sim_x_motor, sim_y_motor])
