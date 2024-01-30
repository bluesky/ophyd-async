import pytest

from ophyd_async.core import Device, DeviceCollector, NotConnected


class Dummy(Device):
    async def connect(self, mock: bool = False):
        raise AttributeError()


def test_device_collector_does_not_propagate_error(RE):
    with pytest.raises(NotConnected) as exc:
        with DeviceCollector():
            _ = Dummy("somename")

    assert not exc.value.__cause__
