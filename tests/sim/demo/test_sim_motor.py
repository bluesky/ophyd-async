import asyncio
import time

from bluesky.plans import spiral_square
from bluesky.run_engine import RunEngine

from ophyd_async.core.device import DeviceCollector
from ophyd_async.sim.demo.sim_motor import SimMotor


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
    while not m1._move_status:
        # wait to actually get the move started
        await asyncio.sleep(0)
    await asyncio.sleep(0.2)
    m1.stop()
    await asyncio.sleep(0)
    new_pos = await m1.user_readback.get_value()

    assert move_status.done
    # move should not be successful as we stopped it
    assert not move_status.success
    assert new_pos < 10
    assert new_pos >= 0.1


async def test_timeout():
    """
    Verify that timeout happens as expected for SimMotor moves.

    This test also verifies that the two tasks involved in the move are
    completed as expected.
    """
    async with DeviceCollector():
        m1 = SimMotor("M1", instant=False)

    # do a 10 sec move that will timeout before arriving
    move_status = m1.set(10, timeout=0.1)
    await asyncio.sleep(0.2)

    # verify status of inner task set up to run _move.update_position()
    assert isinstance(m1._move_task, asyncio.Task)
    assert m1._move_task.done
    assert m1._move_task.cancelled

    # verify status of outer task set up to run _move()
    assert move_status.task.done
    assert move_status.task.cancelled

    new_pos = await m1.user_readback.get_value()
    assert new_pos < 10
    assert move_status.done
    assert not move_status.success
