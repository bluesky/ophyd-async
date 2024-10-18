import asyncio
import traceback
from unittest.mock import Mock

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    DeviceVector,
    NotConnected,
    Reference,
    SignalRW,
    soft_signal_rw,
    wait_for_connection,
)
from ophyd_async.epics import motor
from ophyd_async.plan_stubs import ensure_connected


class DummyBaseDevice(Device):
    def __init__(self) -> None:
        self.connected = False
        super().__init__()

    async def connect(
        self, mock=False, timeout=DEFAULT_TIMEOUT, force_reconnect: bool = False
    ):
        self.connected = True


class DummyDeviceGroup(Device):
    def __init__(self, name: str) -> None:
        self.child1 = DummyBaseDevice()
        self._child2 = DummyBaseDevice()
        self.dict_with_children: DeviceVector[DummyBaseDevice] = DeviceVector(
            {123: DummyBaseDevice()}
        )
        super().__init__(name)


@pytest.fixture
def parent() -> DummyDeviceGroup:
    return DummyDeviceGroup("parent")


class DeviceWithNamedChild(Device):
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self.child = soft_signal_rw(int, name="foo")


def test_device_signal_naming():
    device = DeviceWithNamedChild("bar")
    assert device.name == "bar"
    assert device.child.name == "foo"


class DeviceWithRefToSignal(Device):
    def __init__(self, signal: SignalRW[int]):
        self.signal_ref = Reference(signal)
        super().__init__(name="bat")

    def get_source(self) -> str:
        return self.signal_ref().source


def test_device_with_signal_ref_does_not_rename():
    device = DeviceWithNamedChild()
    device.set_name("bar")
    assert dict(device.children()) == {"child": device.child}
    private_device = DeviceWithRefToSignal(device.child)
    assert device.child.source == private_device.get_source()
    assert dict(private_device.children()) == {}
    assert device.name == "bar"
    assert device.child.name == "bar-child"
    assert private_device.name == "bat"


def test_device_children(parent: DummyDeviceGroup):
    names = ["child1", "_child2", "dict_with_children"]
    for idx, (name, child) in enumerate(parent.children()):
        assert name == names[idx]
        expected_type = (
            DeviceVector if name == "dict_with_children" else DummyBaseDevice
        )
        assert type(child) is expected_type
        assert child.parent == parent


def test_device_vector_children():
    parent = DummyDeviceGroup("root")

    device_vector_children = list(parent.dict_with_children.items())
    assert device_vector_children == [(123, parent.dict_with_children[123])]


async def test_children_of_device_have_set_names_and_get_connected(
    parent: DummyDeviceGroup,
):
    assert parent.name == "parent"
    assert parent.child1.name == "parent-child1"
    assert parent._child2.name == "parent-child2"
    assert parent.dict_with_children.name == "parent-dict_with_children"
    assert parent.dict_with_children[123].name == "parent-dict_with_children-123"

    await parent.connect()

    assert parent.child1.connected
    assert parent.dict_with_children[123].connected


async def test_device_with_device_collector():
    async with DeviceCollector(mock=True):
        parent = DummyDeviceGroup("parent")

    assert parent.name == "parent"
    assert parent.child1.name == "parent-child1"
    assert parent._child2.name == "parent-child2"
    assert parent.dict_with_children.name == "parent-dict_with_children"
    assert parent.dict_with_children[123].name == "parent-dict_with_children-123"
    assert parent.child1.connected
    assert parent.dict_with_children[123].connected


async def test_wait_for_connection():
    class DummyDeviceWithSleep(DummyBaseDevice):
        def __init__(self, name) -> None:
            self.set_name(name)

        async def connect(self, mock=False, timeout=DEFAULT_TIMEOUT):
            await asyncio.sleep(0.01)
            self.connected = True

    device1, device2 = DummyDeviceWithSleep("device1"), DummyDeviceWithSleep("device2")

    normal_coros = {"device1": device1.connect(), "device2": device2.connect()}

    await wait_for_connection(**normal_coros)

    assert device1.connected
    assert device2.connected


async def test_wait_for_connection_propagates_error(
    normal_coroutine, failing_coroutine
):
    failing_coros = {"test": normal_coroutine(), "failing": failing_coroutine()}

    with pytest.raises(NotConnected) as e:
        await wait_for_connection(**failing_coros)
        assert traceback.extract_tb(e.__traceback__)[-1].name == "failing_coroutine"


async def test_device_log_has_correct_name():
    device = DummyBaseDevice()
    assert device.log.extra["ophyd_async_device_name"] == ""
    device.set_name("device")
    assert device.log.extra["ophyd_async_device_name"] == "device"


class MotorBundle(Device):
    def __init__(self, name: str) -> None:
        self.X = motor.Motor("BLxxI-MO-TABLE-01:X")
        self.Y = motor.Motor("BLxxI-MO-TABLE-01:Y")
        self.V: DeviceVector[motor.Motor] = DeviceVector(
            {
                0: motor.Motor("BLxxI-MO-TABLE-21:X"),
                1: motor.Motor("BLxxI-MO-TABLE-21:Y"),
                2: motor.Motor("BLxxI-MO-TABLE-21:Z"),
            }
        )
        super().__init__(name)


async def test_device_with_children_lazily_connects(RE):
    parentMotor = MotorBundle("parentMotor")

    for device in [parentMotor, parentMotor.X, parentMotor.Y] + list(
        parentMotor.V.values()
    ):
        assert device._connect_task is None
    RE(ensure_connected(parentMotor, mock=True))

    for device in [parentMotor, parentMotor.X, parentMotor.Y] + list(
        parentMotor.V.values()
    ):
        assert (
            device._connect_task is not None
            and device._connect_task.done()
            and not device._connect_task.exception()
        )


@pytest.mark.parametrize("use_Mock", [False, True])
async def test_no_reconnect_signals_if_not_forced(use_Mock):
    parent = DummyDeviceGroup("parent")

    connect_mock_arg = Mock() if use_Mock else True

    async def inner_connect(mock, timeout, force_reconnect):
        parent.child1.connected = True

    parent.child1.connect = Mock(side_effect=inner_connect)
    await parent.connect(mock=connect_mock_arg, timeout=0.01)
    assert parent.child1.connected
    assert parent.child1.connect.call_count == 1
    await parent.connect(mock=connect_mock_arg, timeout=0.01)
    assert parent.child1.connected
    assert parent.child1.connect.call_count == 1

    for count in range(2, 10):
        await parent.connect(mock=connect_mock_arg, timeout=0.01, force_reconnect=True)
        assert parent.child1.connected
        assert parent.child1.connect.call_count == count
