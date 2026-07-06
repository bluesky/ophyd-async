import asyncio
from functools import cached_property
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ophyd_async.core import (
    MovableLogic,
    StandardMovable,
    callback_on_mock_put,
    init_devices,
    mock_puts_blocked,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)

# Allow these imports from private modules for tests
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


class StandardMovableImpl(StandardMovable[float]):
    def __init__(self, name: str = ""):
        self.readback, _ = soft_signal_r_and_setter(float)
        self.setpoint = soft_signal_rw(float)
        super().__init__(name=name)

    @cached_property
    def movable_logic(self) -> MovableLogic[float]:
        return MovableLogic(setpoint=self.setpoint, readback=self.readback)


@pytest.fixture
async def movable() -> StandardMovableImpl:
    async with init_devices(mock=True):
        movable = StandardMovableImpl()
    return movable


def test_movable_logic_is_cached(movable: StandardMovableImpl):
    logic = movable.movable_logic
    logic2 = movable.movable_logic

    assert logic == logic2


async def test_movable_check_value(movable: StandardMovableImpl):
    movable.movable_logic.check_move = AsyncMock()
    await movable.check_value(5)
    movable.movable_logic.check_move.assert_awaited_once_with(5)


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


async def test_movable_set_calls_movable_logic_check_move_and_calculate_timeout(
    movable: StandardMovableImpl,
):
    mock_check_move = movable.movable_logic.check_move = AsyncMock()
    timeout = 5
    mock_calculate_timeout = movable.movable_logic.calculate_timeout = AsyncMock(
        return_value=timeout
    )
    mock_move = movable.movable_logic.move = AsyncMock()

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
