import asyncio
import sys
from unittest.mock import patch

import pytest
from bluesky.plans import spiral_square
from bluesky.run_engine import RunEngine

from ophyd_async.core import FlyMotorInfo
from ophyd_async.sim import SimMotor
from ophyd_async.testing import StatusWatcher


async def test_move_sim_in_plan():
    RE = RunEngine()
    m1 = SimMotor("M1")
    m2 = SimMotor("M2")

    my_plan = spiral_square([], m1, m2, 0, 0, 4, 4, 10, 10)

    RE(my_plan)

    assert await m1.user_readback.get_value() == -2
    assert await m2.user_readback.get_value() == -2


@pytest.fixture
def m1() -> SimMotor:
    return SimMotor("M1", instant=False)


@pytest.mark.skipif("win" in sys.platform, reason="windows CI runners too weedy")
@pytest.mark.parametrize(
    "setpoint,expected",
    [
        (-0.19, [0.0, -0.05, -0.1495, -0.19]),
        (0.26, [0.0, 0.05, 0.15, 0.242, 0.26]),
        (0.005, [0.0, 0.005]),
        (-0.025, [0.0, -0.025]),
    ],
)
async def test_move_profiles(setpoint, expected, m1: SimMotor):
    await m1.acceleration_time.set(0.1)
    status = m1.set(setpoint)
    watcher = StatusWatcher(status)
    for i, v in enumerate(expected):
        await watcher.wait_for_call(
            current=pytest.approx(v),
            initial=0.0,
            name="M1",
            target=setpoint,
            time_elapsed=pytest.approx(i * 0.1, abs=0.1),
            unit="mm",
        )
    await status
    watcher.mock.assert_not_called()
    assert await m1.user_readback.get_value() == setpoint


async def test_short_move_is_exactly_move_time(m1: SimMotor):
    with patch("asyncio.sleep") as mock_sleep:
        await m1.set(0.0032)
    mock_sleep.assert_called_once_with(pytest.approx(0.08, abs=0.02))


@pytest.mark.timeout(3)
async def test_stop(m1: SimMotor):
    # this move should take 10 seconds but we will stop it after 0.5
    move_status = m1.set(10)
    await asyncio.sleep(0.5)
    await m1.stop(success=False)
    new_pos = await m1.user_readback.get_value()
    assert new_pos < 10
    assert new_pos >= 0.1

    assert not move_status.success
    with pytest.raises(RuntimeError, match="Motor was stopped"):
        await move_status


@pytest.mark.skipif("win" in sys.platform, reason="windows CI runners too weedy")
async def test_fly(m1: SimMotor):
    await m1.acceleration_time.set(0.1)
    info = FlyMotorInfo(start_position=0, end_position=1, time_for_move=0.2)
    fly_start, fly_end, velocity = -0.25, 1.25, 5
    await m1.prepare(info)
    assert await m1.user_readback.get_value() == fly_start
    assert await m1.velocity.get_value() == velocity
    await m1.kickoff()
    status = m1.complete()
    watcher = StatusWatcher(status)
    for i, v in enumerate([-0.25, 0, 0.5, 1.0, 1.25]):
        await watcher.wait_for_call(
            current=pytest.approx(v),
            initial=fly_start,
            name="M1",
            target=fly_end,
            time_elapsed=pytest.approx(i * 0.1, abs=0.1),
            unit="mm",
        )
    await status
    watcher.mock.assert_not_called()
    assert await m1.user_readback.get_value() == fly_end


async def test_sim_motor_can_be_set_to_its_current_position(m1: SimMotor):
    await m1.set(0)
