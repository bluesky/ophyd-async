import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from functools import cached_property
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ophyd_async.core import (
    KICKED_OFF,
    FlyableLogic,
    MovableLogic,
    StandardFlyable,
    StandardMovable,
    StandardReadable,
    StoppedError,
    WatcherUpdate,
    callback_on_mock_put,
    init_devices,
    mock_puts_blocked,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)

# MoveTimeout is an internal helper StandardMovable constructs to track a
# move's remaining timeout across repeated calculate_timeout() calls - the
# public MovableLogic.calculate_timeout() hook returns a plain float | None,
# never a MoveTimeout, so a caller never sees this type. Tested directly
# here since the reducing-timeout behaviour across repeated calls isn't
# otherwise observable from the public surface - checked, nothing here
# looks missing from the public interface.
from ophyd_async.core._movable import MoveTimeout  # noqa: PLC2701
from ophyd_async.testing import wait_for_pending_wakeups


async def test_move_timeout_repeated_calls_reduces_avaliable_timeout():
    with patch("ophyd_async.core._movable.time.monotonic") as monotonic:
        timeout = 10
        monotonic.return_value = 0
        move_timeout = MoveTimeout(timeout=timeout, start_time=0)
        for elapsed in range(timeout):
            monotonic.return_value = elapsed
            assert move_timeout() == timeout - elapsed


async def test_move_timeout_with_timeout_none_returns_none():
    move_timeout = MoveTimeout(timeout=None, start_time=0)
    for _ in range(3):
        assert move_timeout() is None


class InstantStopMovableLogic(MovableLogic[float]):
    async def ensure_stopped(self) -> None:
        pass


class StandardMovableImpl(StandardMovable[float]):
    def __init__(self, name: str = ""):
        self.readback, _ = soft_signal_r_and_setter(float)
        self.setpoint = soft_signal_rw(float)
        super().__init__(name=name)

    @cached_property
    def logic(self) -> MovableLogic[float]:
        return InstantStopMovableLogic(setpoint=self.setpoint, readback=self.readback)


@pytest.fixture
async def movable() -> StandardMovableImpl:
    async with init_devices(mock=True):
        movable = StandardMovableImpl()
    return movable


def test_logic_is_cached(movable: StandardMovableImpl):
    logic = movable.logic
    logic2 = movable.logic

    assert logic == logic2


async def test_movable_check_value(movable: StandardMovableImpl):
    movable.logic.check_move = AsyncMock()
    await movable.check_value(5)
    movable.logic.check_move.assert_awaited_once_with(5)


async def test_locatable(movable: StandardMovableImpl) -> None:
    callback_on_mock_put(
        movable.setpoint,
        lambda x: set_mock_value(movable.readback, x),
    )
    assert (await movable.locate())["readback"] == 0
    with mock_puts_blocked(movable.setpoint):
        move_status = movable.set(10)
        assert (await movable.locate())["readback"] == 0
    await move_status
    assert (await movable.locate())["readback"] == 10
    assert (await movable.locate())["setpoint"] == 10


async def test_movable_move_timeout(movable: StandardMovableImpl):
    class MyError(Exception):
        pass

    def do_timeout(value):
        # Raise custom exception to be clear it bubbles up
        raise MyError()

    callback_on_mock_put(movable.setpoint, do_timeout)
    s = movable.set(0.3)
    watcher = Mock()
    s.watch(watcher)
    with pytest.raises(MyError):
        await s
    watcher.assert_called_once_with(
        name="movable",
        current=0.0,
        initial=0.0,
        target=0.3,
        time_elapsed=pytest.approx(0.0, abs=0.2),
    )


async def test_movable_moving_stopped(movable: StandardMovableImpl):
    set_mock_put_proceeds(movable.setpoint, False)
    move_status = movable.set(1.5)
    move_status.add_callback(Mock())
    await asyncio.sleep(0.0001)

    assert not move_status.done
    await movable.stop()

    set_mock_put_proceeds(movable.setpoint, True)
    await wait_for_pending_wakeups()

    assert move_status.done
    assert move_status.success is False

    with pytest.raises(RuntimeError, match=f"Device {movable.name} was stopped"):
        await move_status


async def test_movable_set_calls_logic_check_move_and_calculate_timeout(
    movable: StandardMovableImpl,
):
    mock_check_move = movable.logic.check_move = AsyncMock()
    timeout = 5
    mock_calculate_timeout = movable.logic.calculate_timeout = AsyncMock(
        return_value=timeout
    )
    mock_move = movable.logic.move = AsyncMock()

    with patch("ophyd_async.core._movable.MoveTimeout") as move_timeout:
        pos = 10
        await movable.set(pos)

        mock_check_move.assert_awaited_once_with(pos)
        mock_calculate_timeout.assert_awaited_once_with(0, pos)
        mock_move.assert_awaited_once_with(
            new_position=pos, timeout=move_timeout.return_value
        )


async def test_motor_set_with_instant_mock(
    movable: StandardMovableImpl,
):
    """Integration test: use motor.set() with InstantMotorMock.

    This verifies that InstantMotorMock provides all necessary default values
    so device.set() works without errors.
    """
    # Use motor.set() to move the motor - should work without errors
    status = movable.set(100.0)
    await status

    # Verify the move completed successfully
    assert status.done
    assert status.success
    assert await movable.readback.get_value() == 100.0

    # Test another move to ensure it continues to work
    status = movable.set(-50.0)
    await status
    assert status.success
    assert await movable.readback.get_value() == -50.0


async def test_movable_logic_stop_is_deprecated_but_still_called():
    with pytest.deprecated_call(match=r"OldStopLogic.stop\(\) is deprecated"):

        class OldStopLogic(MovableLogic[float]):
            async def stop(self) -> None:
                stopped.append(True)

    stopped: list[bool] = []

    class OldStopMovable(StandardMovable[float]):
        def __init__(self, name: str = ""):
            self.readback, _ = soft_signal_r_and_setter(float)
            self.setpoint = soft_signal_rw(float)
            super().__init__(name=name)

        @cached_property
        def logic(self) -> MovableLogic[float]:
            # The deprecated stop() is turned into ensure_stopped() when the class
            # is made, which pyright can not see
            return OldStopLogic(  # pyright: ignore[reportAbstractUsage]
                setpoint=self.setpoint, readback=self.readback
            )

    async with init_devices(mock=True):
        movable = OldStopMovable()
    await movable.stop()
    assert stopped == [True]


@dataclass
class HeldMoveLogic(MovableLogic[float], FlyableLogic[None, None]):
    """Moves until released or cancelled; records when it was stopped."""

    moving: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list[str] = field(default_factory=list)

    async def move(self, new_position: float, timeout) -> None:
        self.calls.append(f"move {new_position}")
        self.moving.set()
        await self.release.wait()
        set_mock_value(self.setpoint, new_position)

    async def ensure_stopped(self) -> None:
        self.calls.append("ensure_stopped")

    async def prepare_to_fly(
        self, name: str, value: None, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        yield KICKED_OFF


class StageableMovable(StandardReadable, StandardMovable[float]):
    def __init__(self, name: str = ""):
        self.readback, _ = soft_signal_r_and_setter(float)
        self.setpoint = soft_signal_rw(float)
        super().__init__(name=name)

    @cached_property
    def logic(self) -> HeldMoveLogic:
        return HeldMoveLogic(setpoint=self.setpoint, readback=self.readback)


class FlyableMovable(StageableMovable, StandardFlyable[None, None]):
    pass


@pytest.fixture
async def held() -> FlyableMovable:
    async with init_devices(mock=True):
        held = FlyableMovable(name="movable")
    return held


@pytest.mark.parametrize("success", [False, True])
async def test_stop_ends_a_set_with_or_without_error(
    held: FlyableMovable, success: bool
):
    move_status = held.set(1.0)
    await held.logic.moving.wait()

    await held.stop(success=success)

    if success:
        await move_status
    else:
        with pytest.raises(StoppedError, match="Device movable was stopped"):
            await move_status
    assert held.logic.calls == ["move 1.0", "ensure_stopped"]


async def test_stop_before_any_set_and_twice_is_harmless(held: FlyableMovable):
    await held.stop()
    move_status = held.set(1.0)
    await held.logic.moving.wait()
    await held.stop()
    await held.stop()
    with pytest.raises(StoppedError, match="was stopped"):
        await move_status
    # A later set is not affected by the earlier stops
    held.logic.release.set()
    await held.set(2.0)
    assert held.logic.calls == [
        "ensure_stopped",
        "move 1.0",
        "ensure_stopped",
        "ensure_stopped",
        "move 2.0",
    ]


async def test_stop_before_the_set_starts_leaves_the_hardware_alone(
    held: FlyableMovable,
):
    move_status = held.set(1.0)
    await held.stop()
    with pytest.raises(StoppedError, match="was stopped"):
        await move_status
    assert held.logic.calls == ["ensure_stopped"]


async def test_second_set_supersedes_the_first(held: FlyableMovable):
    first = held.set(1.0)
    await held.logic.moving.wait()
    second = held.set(2.0)

    with pytest.raises(StoppedError, match=r"movable: superseded by a new set\(\)"):
        await first
    held.logic.release.set()
    await second
    assert await held.setpoint.get_value() == 2.0
    # Neither set stopped the hardware: the second move retargets it
    assert held.logic.calls == ["move 1.0", "move 2.0"]


# A timeout of the logic's own is not mistaken for a stop
async def test_a_timeout_inside_move_raises_timeout_error(
    movable: StandardMovableImpl,
):
    async def move(new_position: float, timeout) -> None:
        async with asyncio.timeout(0.01):
            await asyncio.Event().wait()

    movable.logic.move = move
    with pytest.raises(TimeoutError):
        await movable.set(1.0)


@pytest.mark.parametrize("flies", [False, True])
async def test_only_a_flyer_stops_a_set_on_stage_and_unstage(flies: bool):
    async with init_devices(mock=True):
        movable = FlyableMovable() if flies else StageableMovable()
    move_status = movable.set(1.0)
    await movable.logic.moving.wait()

    await movable.stage()
    await movable.unstage()

    # A pure movable stages nothing; a flyer gets ready once on stage and stops on
    # unstage, which also halt a set() in progress without ending it
    assert movable.logic.calls == (
        ["move 1.0", "ensure_stopped", "ensure_stopped"] if flies else ["move 1.0"]
    )
    assert not move_status.done
    movable.logic.release.set()
    await move_status


async def test_unstage_stops_the_hardware_of_a_set_in_progress(held: FlyableMovable):
    await held.stage()
    move_status = held.set(1.0)
    await held.logic.moving.wait()

    await held.unstage()

    # Never prepared, but stopped anyway; only stop() ends the set() itself
    assert not move_status.done
    held.logic.release.set()
    await move_status
    assert held.logic.calls == ["ensure_stopped", "move 1.0", "ensure_stopped"]


@dataclass
class HeldFlyLogic(HeldMoveLogic):
    """Its prepare and fly run until released."""

    async def prepare_to_fly(
        self, name: str, value: None, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        yield None
        await self.release.wait()

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        yield KICKED_OFF
        await self.release.wait()


class HeldFlyer(FlyableMovable):
    @cached_property
    def logic(self) -> HeldFlyLogic:
        return HeldFlyLogic(setpoint=self.setpoint, readback=self.readback)


@pytest.mark.parametrize("success", [False, True])
async def test_stop_halts_the_hardware_but_does_not_end_a_prepare_or_fly(
    success: bool,
):
    async with init_devices(mock=True):
        flyer = HeldFlyer(name="flyer")
    await flyer.stage()
    preparing = flyer.prepare(None)
    await wait_for_pending_wakeups()

    await flyer.stop(success=success)

    # Only the hardware was halted: unstage() and a new prepare() end a prepare()
    assert not preparing.done
    flyer.logic.release.set()
    await preparing
    flyer.logic.release.clear()
    await flyer.kickoff()
    flying = flyer.complete()
    await wait_for_pending_wakeups()

    await flyer.stop(success=success)

    assert not flying.done
    flyer.logic.release.set()
    await flying
    # stage() got it ready once, then the two stop()s
    assert flyer.logic.calls.count("ensure_stopped") == 3
    await flyer.unstage()
