import asyncio
from unittest.mock import ANY

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import init_devices
from ophyd_async.epics.tolerable_device import TolerableDevice
from ophyd_async.testing import (
    StatusWatcher,
    callback_on_mock_put,
    mock_puts_blocked,
    set_mock_value,
    wait_for_pending_wakeups,
)


@pytest.fixture
async def sim_tolerable_device():
    async with init_devices(mock=True):
        sim_tolerable_device = TolerableDevice(
            readback_pv="BLxxI-MO-X",
            setpoint_pv="BLxxI-MO-X_RBV",
            name="sim_tolerable_device",
        )
    set_mock_value(sim_tolerable_device.tolerance, 0.1)
    set_mock_value(sim_tolerable_device.user_readback, 0.0)
    set_mock_value(sim_tolerable_device.user_setpoint, 0.0)
    yield sim_tolerable_device


async def test_tolerable_device_set_and_watch(
    sim_tolerable_device: TolerableDevice,
) -> None:
    s = sim_tolerable_device.set(0.55)
    watcher = StatusWatcher(s)
    await watcher.wait_for_call(
        current=0.0,
        initial=0.0,
        target=0.55,
        name="sim_tolerable_device",
        time_elapsed=ANY,
    )
    assert s.done is False
    set_mock_value(sim_tolerable_device.user_readback, 0.45)
    await watcher.wait_for_call(
        current=0.45,
        initial=0.0,
        target=0.55,
        name="sim_tolerable_device",
        time_elapsed=ANY,
    )
    set_mock_value(sim_tolerable_device.user_readback, 0.55)
    await s
    assert s.done is True


async def test_tolerable_device_set_timeout(sim_tolerable_device: TolerableDevice):
    with pytest.raises(asyncio.TimeoutError):
        await sim_tolerable_device.set(0.55, timeout=0.1)


async def test_tolerable_device_stopped(sim_tolerable_device: TolerableDevice):
    s = sim_tolerable_device.set(0.55)
    watcher = StatusWatcher(s)
    await watcher.wait_for_call(
        current=0.0,
        initial=0.0,
        target=0.55,
        name="sim_tolerable_device",
        time_elapsed=ANY,
    )
    set_mock_value(sim_tolerable_device.user_readback, 0.45)
    assert not s.done
    await sim_tolerable_device.stop()

    assert (
        await sim_tolerable_device.user_setpoint.get_value()
        == await sim_tolerable_device.user_readback.get_value()
    )
    await wait_for_pending_wakeups()
    assert s.done
    assert s.success is False


async def test_locatable(sim_tolerable_device: TolerableDevice) -> None:
    callback_on_mock_put(
        sim_tolerable_device.user_setpoint,
        lambda x, *_, **__: set_mock_value(sim_tolerable_device.user_readback, x),
    )
    assert (await sim_tolerable_device.locate())["readback"] == 0
    with mock_puts_blocked(sim_tolerable_device.user_setpoint):
        move_status = sim_tolerable_device.set(10)
        assert (await sim_tolerable_device.locate())["readback"] == 0
    await move_status
    assert (await sim_tolerable_device.locate())["readback"] == 10
    assert (await sim_tolerable_device.locate())["setpoint"] == 10


async def test_subscribable(sim_tolerable_device: TolerableDevice):
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    sim_tolerable_device.subscribe(q.put_nowait)
    assert (await q.get())["sim_tolerable_device-user_readback"]["value"] == 0.0
    set_mock_value(sim_tolerable_device.user_readback, 23)
    assert (await q.get())["sim_tolerable_device-user_readback"]["value"] == 23.0
    sim_tolerable_device.clear_sub(q.put_nowait)
    set_mock_value(sim_tolerable_device.user_readback, 3)
    assert (await sim_tolerable_device.read())["sim_tolerable_device-user_readback"][
        "value"
    ] == 3.0
    assert q.empty()
