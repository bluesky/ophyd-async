import pytest

from ophyd_async.core import init_devices
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._util import _PmacMotorInfo  # noqa: PLC2701
from ophyd_async.testing import set_mock_value


@pytest.fixture
async def sim_motors():
    sim_x_motor = Motor("BLxxI-MO-STAGE-01:X", name="sim_x_motor")
    sim_y_motor = Motor("BLxxI-MO-STAGE-01:Y", name="sim_y_motor")
    async with init_devices(mock=True):
        sim_pmac = PmacIO(
            prefix="Test_PMAC",
            name="sim_pmac",
            raw_motors=[sim_x_motor, sim_y_motor],
            coord_nums=[],
        )
    await sim_x_motor.connect(mock=True)
    await sim_y_motor.connect(mock=True)
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
