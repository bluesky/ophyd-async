import pytest

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceCollector, NotConnected


class Dummy(Device):
    async def connect(self, sim: bool = False, timeout=DEFAULT_TIMEOUT):
        raise AttributeError()


def test_device_collector_handles_top_level_errors(RE, caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected) as exc:
        with DeviceCollector():
            _ = Dummy("somename")

    assert not exc.value.__cause__

    logs = caplog.get_records("call")
    device_log = [
        log
        for log in logs
        if log.message == "device `_` raised unexpected exception AttributeError"
    ]  # In some environments the asyncio teardown will be logged as an error too

    assert len(device_log) == 1
    device_log[0].levelname == "ERROR"
