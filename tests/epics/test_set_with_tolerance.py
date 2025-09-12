import asyncio
from unittest.mock import ANY

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import init_devices
from ophyd_async.epics.set_with_tolerance import SetWithTolerance
from ophyd_async.testing import (
    StatusWatcher,
    callback_on_mock_put,
    mock_puts_blocked,
    set_mock_value,
    wait_for_pending_wakeups,
)


@pytest.fixture
async def sim_set_tolerable():
    async with init_devices(mock=True):
        sim_set_tolerable = SetWithTolerance(
            readback_pv="BLxxI-MO-X",
            setpoint_pv="BLxxI-MO-X_RBV",
            tolerance=0.1,
            name="sim_set_tolerable",
        )
    assert await sim_set_tolerable.tolerance.get_value() == 0.1
    set_mock_value(sim_set_tolerable.user_readback, 0.0)
    set_mock_value(sim_set_tolerable.user_setpoint, 0.0)
    yield sim_set_tolerable


@pytest.mark.parametrize(
    "tolerance, new_position, intermediate_position, final_readback",
    [
        (0.1, 1, 0.5, 0.92),
        (1.5, -3, 4, -2.4),
        (-0.3, -6, -0.25, -5.8),
    ],
)
async def test_set_with_tolerance_set_and_watch(
    sim_set_tolerable: SetWithTolerance,
    tolerance,
    new_position,
    intermediate_position,
    final_readback,
) -> None:
    await sim_set_tolerable.tolerance.set(tolerance)
    set_status = sim_set_tolerable.set(new_position)
    await wait_for_pending_wakeups(max_yields=30)
    watcher = StatusWatcher(set_status)
    await watcher.wait_for_call(
        current=0.0,
        initial=0.0,
        target=new_position,
        name="sim_set_tolerable",
        time_elapsed=ANY,
    )

    assert set_status.done is False
    set_mock_value(sim_set_tolerable.user_readback, intermediate_position)
    await watcher.wait_for_call(
        current=intermediate_position,
        initial=0.0,
        target=new_position,
        name="sim_set_tolerable",
        time_elapsed=ANY,
    )
    assert set_status.done is False
    set_mock_value(sim_set_tolerable.user_readback, final_readback)
    await watcher.wait_for_call(
        current=final_readback,
        initial=0.0,
        target=new_position,
        name="sim_set_tolerable",
        time_elapsed=ANY,
    )
    assert set_status.done is False
    await set_status
    assert set_status.done is True
    assert await sim_set_tolerable.user_readback.get_value() == final_readback


async def test_set_with_tolerance_set_timeout(sim_set_tolerable: SetWithTolerance):
    with pytest.raises(asyncio.TimeoutError):
        await sim_set_tolerable.set(0.55, timeout=0.1)
        await wait_for_pending_wakeups(max_yields=30)

    assert await sim_set_tolerable._timeout.get_value() == 0.1


async def test_set_with_tolerance_stopped(sim_set_tolerable: SetWithTolerance):
    set_status = sim_set_tolerable.set(0.55)
    await wait_for_pending_wakeups(max_yields=30)
    set_mock_value(sim_set_tolerable.user_readback, 0.45)

    assert not set_status.done
    await sim_set_tolerable.stop()

    assert (
        await sim_set_tolerable.user_setpoint.get_value()
        == await sim_set_tolerable.user_readback.get_value()
    )
    with pytest.raises(RuntimeError):
        await set_status
    assert set_status.done
    assert set_status.success is False


async def test_set_with_tolerance_double_set_success(
    sim_set_tolerable: SetWithTolerance,
):
    set_status = sim_set_tolerable.set(0.55)
    set_status2 = sim_set_tolerable.set(0.45)
    await wait_for_pending_wakeups(max_yields=30)
    set_mock_value(sim_set_tolerable.user_readback, 0.45)

    await set_status2
    assert set_status2.done == set_status.done is True
    assert set_status2.success == set_status.success is True


async def test_set_with_tolerance_change_tolerance_success(
    sim_set_tolerable: SetWithTolerance,
):
    await sim_set_tolerable.tolerance.set(0)
    set_status = sim_set_tolerable.set(0.55)
    set_mock_value(sim_set_tolerable.user_readback, 0.45)

    assert set_status.done is False
    await sim_set_tolerable.tolerance.set(1)
    await set_status
    assert set_status.done
    assert set_status.success


async def test_locatable(sim_set_tolerable: SetWithTolerance) -> None:
    callback_on_mock_put(
        sim_set_tolerable.user_setpoint,
        lambda x, *_, **__: set_mock_value(sim_set_tolerable.user_readback, x),
    )
    assert (await sim_set_tolerable.locate())["readback"] == 0
    with mock_puts_blocked(sim_set_tolerable.user_setpoint):
        move_status = sim_set_tolerable.set(10)
        assert (await sim_set_tolerable.locate())["readback"] == 0
    await move_status
    assert (await sim_set_tolerable.locate())["readback"] == 10
    assert (await sim_set_tolerable.locate())["setpoint"] == 10


async def test_subscribable(sim_set_tolerable: SetWithTolerance):
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    sim_set_tolerable.subscribe(q.put_nowait)
    assert (await q.get())["sim_set_tolerable"]["value"] == 0.0
    set_mock_value(sim_set_tolerable.user_readback, 23)
    assert (await q.get())["sim_set_tolerable"]["value"] == 23.0
    sim_set_tolerable.clear_sub(q.put_nowait)
    set_mock_value(sim_set_tolerable.user_readback, 3)
    assert (await sim_set_tolerable.read())["sim_set_tolerable"]["value"] == 3.0
    assert q.empty()
