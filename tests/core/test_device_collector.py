import pytest

from ophyd_async.core import DEFAULT_TIMEOUT, Device, DeviceCollector, NotConnected


class Dummy(Device):
    async def connect(self, sim: bool = False, timeout=DEFAULT_TIMEOUT):
        raise AttributeError()


def test_device_collector_does_not_propagate_error(RE):
    with pytest.raises(NotConnected) as exc:
        with DeviceCollector():
            _ = Dummy("somename")

    assert not exc.value.__cause__
