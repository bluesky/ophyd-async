import asyncio

import pytest
from bluesky import plan_stubs as bps
from bluesky.run_engine import RunEngine, TransitionError

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceCollector, NotConnected
from ophyd_async.epics.motion import motor


class FailingDevice(Device):
    async def connect(self, sim: bool = False, timeout=DEFAULT_TIMEOUT):
        raise AttributeError()


class WorkingDevice(Device):
    connected = False

    async def connect(self, sim: bool = True, timeout=DEFAULT_TIMEOUT):
        self.connected = True
        return await super().connect(sim=True)

    async def set(self, new_position: float): ...


async def test_device_collector_handles_top_level_errors(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected) as exc:
        async with DeviceCollector():
            _ = FailingDevice("somename")

    assert not exc.value.__cause__

    logs = caplog.get_records("call")
    device_log = [
        log
        for log in logs
        if log.message == "device `_` raised unexpected exception AttributeError"
    ]  # In some environments the asyncio teardown will be logged as an error too

    assert len(device_log) == 1
    device_log[0].levelname == "ERROR"


def test_device_connector_sync_no_run_engine_raises_error():
    with pytest.raises(NotConnected) as e:
        with DeviceCollector():
            working_device = WorkingDevice("somename")
    assert e.value._errors == (
        "Could not connect devices. Is the bluesky event loop running? See "
        "https://blueskyproject.io/ophyd-async/main/"
        "user/explanations/event-loop-choice.html for more info."
    )
    assert not working_device.connected


def test_device_connector_sync_run_engine_created_connects(RE):
    with DeviceCollector():
        working_device = WorkingDevice("somename")

    assert working_device.connected


def test_device_connector_async_run_engine_same_event_loop():
    async def set_up_device():
        async with DeviceCollector(sim=True):
            sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        return sim_motor

    loop = asyncio.new_event_loop()
    checking_loop = asyncio.new_event_loop()

    try:
        sim_motor = loop.run_until_complete(set_up_device())
        RE = RunEngine(call_returns_result=True, loop=loop)

        def my_plan():
            yield from bps.mov(sim_motor, 3.14)

        RE(my_plan())

        assert (
            checking_loop.run_until_complete(sim_motor.setpoint.read())[
                "sim_motor-setpoint"
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


"""
# SimSignalBackend currently allows a different event loop to set the value
# so this test is not working
def test_device_connector_async_run_engine_different_event_loop():
    async def set_up_device():
        async with DeviceCollector(sim=True):
            sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
        return sim_motor

    device_connector_loop = asyncio.new_event_loop()
    run_engine_loop = asyncio.new_event_loop()
    assert run_engine_loop is not device_connector_loop

    sim_motor = device_connector_loop.run_until_complete(set_up_device())

    RE = RunEngine(loop=run_engine_loop)
    def my_plan():
        yield from bps.mov(sim_motor, 3.14)
    RE(my_plan())

    # The set should fail since the run engine is on a different event loop
    assert (
        device_connector_loop.run_until_complete(sim_motor.setpoint.read())[
            "sim_motor-setpoint"
        ]["value"]
        != 3.14
    )
"""
