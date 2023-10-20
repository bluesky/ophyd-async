import pytest

from ophyd_async.core import Device, DeviceCollector


class Dummy(Device):
    def connect(self, sim: bool = False):
        raise AttributeError()


def test_device_collector_propagates_error(RE):
    with pytest.raises(AttributeError):
        with DeviceCollector():
            _ = Dummy("somename")
