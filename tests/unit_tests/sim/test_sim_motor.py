import asyncio
import sys
from unittest.mock import call, patch

import pytest
from bluesky.plans import spiral_square
from bluesky.protocols import Reading
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


@pytest.fixture(params=[True, False])
def m1(
    request: pytest.FixtureRequest,
) -> SimMotor:
    return SimMotor("M1", instant=request.param)


@pytest.fixture
def m2() -> SimMotor:
    return SimMotor("M2", instant=False)


@pytest.mark.xfail(reason="Flaky test")
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


async def test_short_move_is_exactly_move_time(m2: SimMotor):
    with patch("asyncio.sleep") as mock_sleep:
        await m2.set(0.0032)
    mock_sleep.assert_has_calls([call(pytest.approx(0.08, abs=0.02))])


@pytest.mark.timeout(3)
async def test_stop(m2: SimMotor):
    # this move should take 10 seconds but we will stop it partway through.
    # The sim motor updates its readback at 10Hz, so 0.2s is two update ticks
    # in - enough for the readback to have moved off 0 without waiting longer.
    move_status = m2.set(10)
    await asyncio.sleep(0.2)
    await m2.stop(success=False)
    new_pos = await m2.user_readback.get_value()
    assert 0 < new_pos < 10

    assert not move_status.success
    with pytest.raises(RuntimeError, match=f"Device {m2.name} was stopped"):
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


async def test_sim_motor_initial_readback_matches_initial_value():
    initial_value = 600
    motor = SimMotor(initial_value=initial_value, instant=False)
    readback, setpoint = await asyncio.gather(
        motor.user_readback.get_value(), motor.user_setpoint.get_value()
    )
    assert readback == setpoint == initial_value


@pytest.mark.parametrize(
    ("target", "direction"),
    [
        (600.5, 1),  # low -> high
        (599.5, -1),  # high -> low
    ],
)
async def test_sim_motor_move(target: float, direction: int):
    initial_value = 600.0

    motor = SimMotor(initial_value=initial_value, instant=False, name="motor")
    await motor.connect()

    readbacks: list[float] = []

    def on_readback(value: dict[str, Reading[float]]) -> None:
        readbacks.append(value[motor.user_readback.name]["value"])

    motor.user_readback.subscribe(on_readback)

    await motor.set(target)
    readback, setpoint = await asyncio.gather(
        motor.user_setpoint.get_value(), motor.user_readback.get_value()
    )
    assert readback == setpoint == target
    assert len(readbacks) > 2
    assert readbacks[-1] == pytest.approx(target)

    # Motion must be monotonic.
    assert all(
        (current - previous) * direction >= 0
        for previous, current in zip(readbacks, readbacks[1:], strict=False)
    )
    # No overshoot.
    lower = min(initial_value, target)
    upper = max(initial_value, target)

    assert all(lower <= value <= upper for value in readbacks)


@pytest.mark.parametrize("instant", [True, False])
async def test_sim_motor_move_mode(instant: bool):
    motor = SimMotor(initial_value=600.0, instant=instant, name="motor")
    await motor.connect()

    readbacks: list[float] = []

    def on_readback(value: dict[str, Reading[float]]) -> None:
        readbacks.append(value[motor.user_readback.name]["value"])

    motor.user_readback.subscribe(on_readback)

    await motor.set(600.05)

    assert readbacks[-1] == pytest.approx(600.05)

    if instant:
        # The motor should move directly to the target.
        assert readbacks == [600, 600.05]
    else:
        # The motor should have produced intermediate positions.
        assert len(readbacks) > 2
        assert any(600.0 < value < 600.05 for value in readbacks)

        # Motion should be monotonic.
        assert all(
            previous <= current
            for previous, current in zip(readbacks, readbacks[1:], strict=False)
        )
