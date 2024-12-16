import asyncio

import pytest
from bluesky import plan_stubs as bps
from bluesky.run_engine import RunEngine, TransitionError

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    NotConnected,
    init_devices,
)
from ophyd_async.epics import motor
from ophyd_async.testing import set_mock_value


class FailingDevice(Device):
    async def connect(
        self, mock: bool = False, timeout=DEFAULT_TIMEOUT, force_reconnect=False
    ):
        raise AttributeError()


class WorkingDevice(Device):
    connected = False

    async def connect(
        self, mock: bool = True, timeout=DEFAULT_TIMEOUT, force_reconnect=False
    ):
        self.connected = True
        return await super().connect(mock=True)

    async def set(self, new_position: float): ...


async def test_init_devices_handles_top_level_errors(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected) as exc:
        async with init_devices():
            _ = FailingDevice("somename")

    assert not exc.value.__cause__

    logs = caplog.get_records("call")
    device_log = [
        log
        for log in logs
        if log.message == "device `_` raised unexpected exception AttributeError"
    ]  # In some environments the asyncio teardown will be logged as an error too

    assert len(device_log) == 1
    assert device_log[0].levelname == "ERROR"


def test_sync_init_devices_no_run_engine_raises_error():
    with pytest.raises(NotConnected) as e:
        with init_devices():
            working_device = WorkingDevice("somename")
    assert e.value._errors == (
        "Could not connect devices. Is the bluesky event loop running? See "
        "https://blueskyproject.io/ophyd-async/main/"
        "user/explanations/event-loop-choice.html for more info."
    )
    assert not working_device.connected


def test_sync_init_devices_run_engine_created_connects(RE):
    with init_devices():
        working_device = WorkingDevice("somename")

    assert working_device.connected


async def test_init_devices_detects_redeclared_devices():
    original_working_device = working_device = WorkingDevice()

    async with init_devices():
        working_device = WorkingDevice()
    assert original_working_device is not working_device
    assert working_device.connected and working_device.name == "working_device"
    assert not original_working_device.connected and original_working_device.name == ""


def test_connecting_in_plan_raises(RE):
    def bad_plan():
        yield from bps.null()
        with init_devices():
            working_device = WorkingDevice("somename")  # noqa: F841

    with pytest.raises(RuntimeError, match="Cannot use DeviceConnector inside a plan"):
        RE(bad_plan())


def test_async_init_devices_run_engine_same_event_loop():
    async def set_up_device():
        async with init_devices(mock=True):
            mock_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        set_mock_value(mock_motor.velocity, 1)
        return mock_motor

    loop = asyncio.new_event_loop()
    checking_loop = asyncio.new_event_loop()

    try:
        mock_motor = loop.run_until_complete(set_up_device())
        RE = RunEngine(call_returns_result=True, loop=loop)

        def my_plan():
            yield from bps.mov(mock_motor, 3.14)

        RE(my_plan())

        assert (
            checking_loop.run_until_complete(mock_motor.user_setpoint.read())[
                "mock_motor-user_setpoint"
            ]["value"]
            == 3.14
        )

    finally:
        if RE.state not in ("idle", "panicked"):
            try:
                RE.halt()
            except TransitionError:
                pass
        loop.call_soon_threadsafe(loop.stop)
        checking_loop.call_soon_threadsafe(checking_loop.stop)
        RE._th.join()
        loop.close()
        checking_loop.close()


@pytest.mark.skip(
    reason=(
        "MockSignalBackend currently allows a different event-"
        "loop to set the value, unlike real signals."
    )
)
def test_async_init_devices_run_engine_different_event_loop():
    async def set_up_device():
        async with init_devices(mock=True):
            mock_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        return mock_motor

    init_devices_loop = asyncio.new_event_loop()
    run_engine_loop = asyncio.new_event_loop()
    assert run_engine_loop is not init_devices_loop

    mock_motor = init_devices_loop.run_until_complete(set_up_device())

    RE = RunEngine(loop=run_engine_loop)

    def my_plan():
        yield from bps.mov(mock_motor, 3.14)

    RE(my_plan())

    # The set should fail since the run engine is on a different event loop
    assert (
        init_devices_loop.run_until_complete(mock_motor.user_setpoint.read())[
            "mock_motor-user_setpoint"
        ]["value"]
        != 3.14
    )
