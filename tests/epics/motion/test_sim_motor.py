import time

from bluesky.plans import spiral_square
from bluesky.run_engine import RunEngine
from ophyd_async.core import set_sim_value
from ophyd_async.epics.motion.sim_motor import SimMotor


async def test_move_sim_in_plan():
    RE = RunEngine()

    m1 = SimMotor("M1", "sim_motor1")
    m2 = SimMotor("M2", "sim_motor2")
    await m1.connect(sim=True)
    await m2.connect(sim=True)

    my_plan = spiral_square([], m1, m2, 0, 0, 4, 4, 10, 10)

    RE(my_plan)

    assert await m1.user_readback.get_value() == -2
    assert await m2.user_readback.get_value() == -2


async def test_slow_move():
    _ = RunEngine()

    m1 = SimMotor("M1", "sim_motor1", instant=False)
    await m1.connect(sim=True)
    set_sim_value(m1.velocity, 10)

    start = time.monotonic()
    m1.move(10)
    elapsed = time.monotonic() - start

    assert elapsed >= 1
    assert elapsed < 2
    assert await m1.user_readback.get_value() == 10
