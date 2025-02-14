import asyncio
import time

import pytest
from bluesky.plans import spiral_square
from bluesky.run_engine import RunEngine

from ophyd_async.sim import FlySimMotorInfo, SimMotor


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


async def test_slow_move(m1: SimMotor):
    await m1.velocity.set(20)
    await m1.acceleration_time.set(0.1)

    start = time.monotonic()
    await m1.set(10)
    elapsed = time.monotonic() - start

    assert await m1.user_readback.get_value() == 10
    assert elapsed >= 0.5
    assert elapsed < 1


@pytest.mark.parametrize(
    "setpoint,expected",
    [
        (-0.19, [0.0, -0.05, -0.1495, -0.19]),
        (0.26, [0.0, 0.05, 0.15, 0.242, 0.26]),
    ],
)
async def test_move_profiles(setpoint, expected, m1: SimMotor):
    await m1.acceleration_time.set(0.1)
    status = m1.set(setpoint)
    updates = []
    status.watch(lambda **kwargs: updates.append(kwargs))
    await status
    assert await m1.user_readback.get_value() == setpoint
    assert updates == [
        {
            "current": pytest.approx(v),
            "initial": 0.0,
            "name": "M1",
            "target": setpoint,
            "time_elapsed": pytest.approx(i * 0.1, abs=0.05),
            "unit": "mm",
        }
        for i, v in enumerate(expected)
    ]


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


async def test_fly(m1: SimMotor):
    await m1.acceleration_time.set(0.1)
    info = FlySimMotorInfo(cv_start=0, cv_end=1, cv_time=0.2)
    fly_start, fly_end, velocity = -0.25, 1.25, 5
    await m1.prepare(info)
    assert await m1.user_readback.get_value() == fly_start
    assert await m1.velocity.get_value() == velocity
    await m1.kickoff()
    status = m1.complete()
    updates = []
    status.watch(lambda **kwargs: updates.append(kwargs))
    await status
    assert await m1.user_readback.get_value() == fly_end
    assert updates == [
        {
            "current": pytest.approx(v),
            "initial": fly_start,
            "name": "M1",
            "target": fly_end,
            "time_elapsed": pytest.approx(i * 0.1, abs=0.05),
            "unit": "mm",
        }
        for i, v in enumerate([-0.25, 0, 0.5, 1.0, 1.25])
    ]
