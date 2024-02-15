import pytest

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceCollector, NotConnected


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


"""
# TODO: Once passing a loop into the run-engine selector works, this should pass
async def test_device_connector_async_run_engine_same_event_loop():
    async with DeviceCollector(sim=True):
        sim_motor = motor.Motor("BLxxI-MO-TABLE-01:X")

    RE = RunEngine(loop=asyncio.get_running_loop())

    def my_plan():
        sim_motor.move(3.14)
        return

    RE(my_plan())

    assert await sim_motor.readback.get_value() == 3.14
"""
