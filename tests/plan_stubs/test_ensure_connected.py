import re

import pytest

from ophyd_async.core import Device, NotConnected, soft_signal_rw
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.plan_stubs import ensure_connected


def test_ensure_connected(RE):
    class MyDevice(Device):
        def __init__(self, prefix: str, name=""):
            self.signal = epics_signal_rw(str, f"pva://{prefix}:SIGNAL")
            super().__init__(name=name)

    device1 = MyDevice("PREFIX1", name="device1")

    def connect():
        yield from ensure_connected(device1, mock=False, timeout=0.1)

    with pytest.raises(
        NotConnected,
        match="device1: NotConnected:\n    signal: NotConnected: pva://PREFIX1:SIGNAL",
    ):
        RE(connect())

    assert isinstance(device1.signal._connect_task.exception(), NotConnected)

    device1.signal = soft_signal_rw(str)
    RE(connect())
    assert device1.signal._connect_task.exception() is None

    device2 = MyDevice("PREFIX2", name="device2")

    def connect_with_mocking():
        assert device2.signal._mock is None
        yield from ensure_connected(device2, mock=True, timeout=0.1)
        assert device2.signal._mock is not None

    RE(connect_with_mocking())


def test_ensure_connected_fails_for_non_unique_device_names(RE):
    d1 = Device("dupe")
    d2 = Device("dupe")
    d3 = Device("ok")
    non_unique = {d1: "dupe", d2: "dupe"}
    with pytest.raises(
        ValueError,
        match=re.escape(f"Devices do not have unique names {non_unique}"),
    ):
        RE(ensure_connected(d1, d2, d3))
