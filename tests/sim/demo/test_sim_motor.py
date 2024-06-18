import asyncio
import time

from bluesky.plans import spiral_square
from bluesky.run_engine import RunEngine

from ophyd_async.core import DeviceCollector
from ophyd_async.sim.demo import SimMotor


async def test_move_sim_in_plan():
    RE = RunEngine()

    async with DeviceCollector():
        m1 = SimMotor("M1")
        m2 = SimMotor("M2")

    my_plan = spiral_square([], m1, m2, 0, 0, 4, 4, 10, 10)

    RE(my_plan)

    assert await m1.user_readback.get_value() == -2
    assert await m2.user_readback.get_value() == -2


async def test_slow_move():
    async with DeviceCollector():
        m1 = SimMotor("M1", instant=False)

    await m1.velocity.set(20)

    start = time.monotonic()
    await m1.set(10)
    elapsed = time.monotonic() - start

    assert await m1.user_readback.get_value() == 10
    assert elapsed >= 0.5
    assert elapsed < 1


async def test_stop():
    async with DeviceCollector():
        m1 = SimMotor("M1", instant=False)

    # this move should take 10 seconds but we will stop it after 0.2
    move_status = m1.set(10)
    await asyncio.sleep(0.2)
    await m1.stop(success=False)
    new_pos = await m1.user_readback.get_value()
    assert new_pos < 10
    assert new_pos >= 0.1
    # move should not be successful as we stopped it
    assert move_status.done
    assert not move_status.success
