import asyncio
import sys
import threading
from unittest.mock import Mock, call, patch

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import pytest
from bluesky.plans import spiral_square
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine
from bluesky.utils import FailedStatus, RunEngineInterrupted

from ophyd_async.core import (
    Device,
    FlyMotorInfo,
    StoppedError,
    WatchableAsyncStatus,
    forward_watcher_updates,
)
from ophyd_async.sim import SimMotor


class TwoMotorStage(Device):
    def __init__(self, combine: bool, name: str = ""):
        self.x = SimMotor(instant=False)
        self.y = SimMotor(instant=False)
        self._combine = combine
        super().__init__(name=name)

    @WatchableAsyncStatus.wrap
    async def set(self, value: tuple[float, float]):
        statuses = [self.x.set(value[0]), self.y.set(value[1])]
        async for update in forward_watcher_updates(
            statuses, self.name, combine=self._combine
        ):
            yield update


@pytest.mark.parametrize("combine", [True, False])
async def test_device_forwards_progress_of_two_moving_motors(combine: bool):
    stage = TwoMotorStage(combine, name="stage")
    for motor in (stage.x, stage.y):
        await asyncio.gather(motor.velocity.set(10.0), motor.acceleration_time.set(0.1))
    watcher = Mock()
    status = stage.set((1.0, 2.0))
    status.watch(watcher)
    await status

    x, y = await asyncio.gather(
        stage.x.user_readback.get_value(), stage.y.user_readback.get_value()
    )
    assert x == 1.0
    assert y == 2.0
    updates = [c.kwargs for c in watcher.call_args_list]
    if combine:
        assert {u["name"] for u in updates} == {"stage"}
        currents = [u["current"] for u in updates]
        assert currents == sorted(currents)
        assert 0.0 < currents[len(currents) // 2] < 1.0
        assert updates[-1]["current"] == pytest.approx(1.0)
        assert updates[-1]["fraction"] == pytest.approx(0.0)
    else:
        for name, target in (("stage-x", 1.0), ("stage-y", 2.0)):
            currents = [u["current"] for u in updates if u["name"] == name]
            assert len(currents) > 2
            assert currents == sorted(currents)
            assert currents[-1] == target


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


async def test_short_move_is_exactly_move_time(m2: SimMotor):
    with patch("asyncio.sleep") as mock_sleep:
        await m2.set(0.0032)
    mock_sleep.assert_has_calls([call(pytest.approx(0.08, abs=0.02))])


@pytest.mark.timeout(3)
@pytest.mark.parametrize("moving", [False, True], ids=["before_motion", "moving"])
@pytest.mark.parametrize("success", [False, True])
async def test_stop(m2: SimMotor, success: bool, moving: bool):
    # this move should take 10 seconds but we will stop it partway through.
    # The sim motor updates its readback at 10Hz, so 0.2s is two update ticks
    # in - enough for the readback to have moved off 0 without waiting longer.
    move_status = m2.set(10)
    if moving:
        await asyncio.sleep(0.2)
    await m2.stop(success=success)
    new_pos = await m2.user_readback.get_value()
    assert (0 < new_pos < 10) if moving else new_pos == 0

    if success:
        await move_status
        assert move_status.success
    else:
        assert not move_status.success
        with pytest.raises(StoppedError, match=f"Device {m2.name} was stopped"):
            await move_status
    # Nothing is left moving
    await asyncio.sleep(0.3)
    assert await m2.user_readback.get_value() == new_pos


@pytest.mark.timeout(3)
async def test_second_set_supersedes_the_first(m2: SimMotor):
    first = m2.set(10)
    await asyncio.sleep(0.2)
    second = m2.set(0.5)

    with pytest.raises(StoppedError, match=r"M2: superseded by a new set\(\)"):
        await first
    await second
    # Only the second move is left moving the motor, and it has finished
    assert await m2.user_readback.get_value() == 0.5
    await asyncio.sleep(0.3)
    assert await m2.user_readback.get_value() == 0.5


@pytest.mark.timeout(3)
async def test_unstage_stops_a_fly_and_waits_for_it(m2: SimMotor):
    await asyncio.gather(m2.velocity.set(10), m2.acceleration_time.set(0.05))
    await m2.stage()
    await m2.prepare(FlyMotorInfo(start_position=0, end_position=5, time_for_move=1))
    await m2.kickoff()
    status = m2.complete()
    await asyncio.sleep(0.2)

    await m2.unstage()

    # Already stopped when unstage returns, not stopping soon after
    with pytest.raises(asyncio.CancelledError):
        await status
    stopped_at = await m2.user_readback.get_value()
    assert 0 < stopped_at < 5
    assert await m2.user_setpoint.get_value() == stopped_at
    await asyncio.sleep(0.3)
    assert await m2.user_readback.get_value() == stopped_at


@pytest.mark.timeout(5)
@pytest.mark.parametrize("success", [False, True])
async def test_stop_during_a_fly_halts_the_motor_and_ends_complete(
    m2: SimMotor, success: bool
):
    await asyncio.gather(m2.velocity.set(10), m2.acceleration_time.set(0.05))
    await m2.stage()
    await m2.prepare(FlyMotorInfo(start_position=0, end_position=2, time_for_move=1))
    await m2.kickoff()
    status = m2.complete()
    await asyncio.sleep(0.2)

    await m2.stop(success=success)

    # As for a real motor, the fly ends early where the motor stopped
    await status
    stopped_at = await m2.user_readback.get_value()
    assert 0 < stopped_at < 2
    await asyncio.sleep(0.3)
    assert await m2.user_readback.get_value() == stopped_at
    await m2.unstage()


@pytest.mark.skipif("win" in sys.platform, reason="windows CI runners too weedy")
async def test_fly(m1: SimMotor):
    await m1.acceleration_time.set(0.1)
    info = FlyMotorInfo(start_position=0, end_position=1, time_for_move=0.2)
    fly_start, fly_end, velocity = -0.25, 1.25, 5
    await m1.stage()
    await m1.prepare(info)
    assert await m1.user_readback.get_value() == fly_start
    assert await m1.velocity.get_value() == velocity
    await m1.kickoff()
    status = m1.complete()
    watcher = Mock()
    status.watch(watcher)
    await status
    # Progress is reported from where the motor is when complete is called
    # (it has been running up for the acceleration time) to the end
    updates = [c.kwargs for c in watcher.call_args_list]
    currents = [u["current"] for u in updates]
    assert currents == sorted(currents)
    assert currents[-1] == pytest.approx(fly_end)
    assert {(u["initial"], u["target"], u["name"], u["unit"]) for u in updates} == {
        (fly_start, fly_end, "M1", "mm")
    }
    assert await m1.user_readback.get_value() == fly_end


@pytest.mark.timeout(3)
async def test_unstage_during_kickoff_run_up_leaves_no_move_running(m2: SimMotor):
    await m2.acceleration_time.set(0.5)
    await m2.stage()
    await m2.prepare(FlyMotorInfo(start_position=0, end_position=5, time_for_move=1))
    kickoff_status = m2.kickoff()
    await asyncio.sleep(0.2)
    await m2.unstage()
    with pytest.raises(asyncio.CancelledError):
        await kickoff_status
    # The readback updates at 10Hz, so a move still running would change it
    stopped_at = await m2.user_readback.get_value()
    await asyncio.sleep(0.3)
    assert await m2.user_readback.get_value() == stopped_at


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
    # Fast enough to keep the test short, slow enough for several 10Hz updates
    await motor.velocity.set(5.0)
    await motor.acceleration_time.set(0.1)

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


FLY_INFO = FlyMotorInfo(start_position=0, end_position=1, time_for_move=0.3)
FLY_END = FLY_INFO.ramp_down_end_pos(0.05)


async def make_fast_motor() -> SimMotor:
    motor = SimMotor("M", instant=False)
    await asyncio.gather(motor.velocity.set(20), motor.acceleration_time.set(0.05))
    return motor


def move_and_fly_plan(
    motor: SimMotor, move_to: float, hang: str | None = None, fail: bool = False
):
    """Move then fly the motor in a run, hanging in `hang` ("move" or "fly") if given.

    The hang ends in a failure if `fail`, otherwise it waits to be interrupted.
    """

    def hang_then_fail():
        yield from bps.sleep(0.3)
        if fail:
            raise ValueError("plan failed")
        yield from bps.sleep(5)

    @bpp.run_decorator()
    @bpp.stage_decorator([motor])
    def plan():
        if hang == "move":
            yield from bps.abs_set(motor, 1000, group="move")
            yield from hang_then_fail()
        yield from bps.mv(motor, move_to)
        yield from bps.prepare(motor, FLY_INFO, wait=True)
        yield from bps.kickoff(motor, wait=True)
        if hang == "fly":
            yield from bps.complete(motor, group="fly")
            yield from hang_then_fail()
        yield from bps.complete(motor, wait=True)

    return plan()


async def test_staged_plans_back_to_back_move_and_fly_the_same_motor():
    RE = RunEngine()
    motor = await make_fast_motor()
    for move_to in (3, -2):
        RE(move_and_fly_plan(motor, move_to))
        assert await motor.user_readback.get_value() == pytest.approx(FLY_END)
        assert await motor.user_setpoint.get_value() == pytest.approx(FLY_END)


@pytest.mark.timeout(20)
@pytest.mark.parametrize("hang", ["move", "fly"])
@pytest.mark.parametrize("interrupt", ["fail", "pause_then_abort"])
async def test_a_plan_interrupted_mid_move_or_fly_leaves_the_motor_ready_for_the_next(
    hang: str, interrupt: str
):
    RE = RunEngine()
    motor = await make_fast_motor()
    if interrupt == "fail":
        # unstage ends the move or fly, which bluesky reports as a FailedStatus
        with pytest.raises((ValueError, FailedStatus)):
            RE(move_and_fly_plan(motor, 3, hang=hang, fail=True))
    else:
        threading.Timer(0.5, RE.request_pause).start()
        with pytest.raises(RunEngineInterrupted):
            RE(move_and_fly_plan(motor, 3, hang=hang))
        RE.abort()
    # Nothing is left moving the motor
    stopped_at = await motor.user_readback.get_value()
    await asyncio.sleep(0.3)
    assert await motor.user_readback.get_value() == stopped_at

    RE(move_and_fly_plan(motor, 3))
    assert await motor.user_readback.get_value() == pytest.approx(FLY_END)
