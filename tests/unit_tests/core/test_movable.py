import asyncio
from asyncio import CancelledError, Event, get_event_loop
from functools import cached_property
from unittest.mock import AsyncMock, Mock

import pytest

from ophyd_async.core import (
    MovableLogic,
    StandardMovable,
    callback_on_mock_put,
    get_mock_put,
    init_devices,
    mock_puts_blocked,
    set_mock_put_proceeds,
    set_mock_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.testing import wait_for_pending_wakeups


class StandardMovableImpl(StandardMovable):
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
    s = movable.set(1.5)
    s.add_callback(Mock())
    await asyncio.sleep(0.0001)

    assert not s.done
    await movable.stop()

    set_mock_put_proceeds(movable.setpoint, True)
    await wait_for_pending_wakeups()

    assert s.done
    assert s.success is False


async def test_cancellederror_in_set_ensures_movable_setpoint_set_task_is_cancelled(
    movable: StandardMovableImpl,
):
    sleep_result = get_event_loop().create_future()
    block_until_ready = Event()

    async def wait_forever_in_setpoint_set(value: float, *args, **kwargs):
        try:
            block_until_ready.set()
            await asyncio.sleep(0.5)
            sleep_result.set_result(None)
        except CancelledError as e:
            sleep_result.set_exception(e)
            raise

    get_mock_put(movable.setpoint).side_effect = wait_forever_in_setpoint_set

    status = movable.set(1)
    await block_until_ready.wait()
    assert status.task.cancel()
    with pytest.raises(CancelledError):
        await status
    with pytest.raises(CancelledError):
        await sleep_result
    assert sleep_result.done()
    assert isinstance(sleep_result.exception(), CancelledError)


async def test_movable_set_calls_movable_logic_check_move_and_calculate_timeout(
    movable: StandardMovableImpl,
):
    mock_check_move = movable.movable_logic.check_move = AsyncMock()
    mock_calculate_timeout = movable.movable_logic.calculate_timeout = AsyncMock(
        return_value=5
    )
    await movable.set(10)

    mock_check_move.assert_awaited_once_with(0, 10)
    mock_calculate_timeout.assert_awaited_once_with(0, 10)


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
