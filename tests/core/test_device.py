import asyncio
import traceback
from unittest.mock import Mock

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    DeviceVector,
    MockSignalBackend,
    NotConnected,
    SoftSignalBackend,
    wait_for_connection,
)
from ophyd_async.epics import motor
from ophyd_async.plan_stubs import ensure_connected
from ophyd_async.sim.demo import SimMotor


class DummyBaseDevice(Device):
    def __init__(self) -> None:
        self.connected = False

    async def connect(
        self, mock=False, timeout=DEFAULT_TIMEOUT, force_reconnect: bool = False
    ):
        self.connected = True


class DummyDeviceGroup(Device):
    def __init__(self, name: str) -> None:
        self.child1 = DummyBaseDevice()
        self.child2 = DummyBaseDevice()
        self.dict_with_children: DeviceVector[DummyBaseDevice] = DeviceVector(
            {123: DummyBaseDevice()}
        )
        self.set_name(name)


@pytest.fixture
def parent() -> DummyDeviceGroup:
    return DummyDeviceGroup("parent")


def test_device_children(parent: DummyDeviceGroup):
    names = ["child1", "child2", "dict_with_children"]
    for idx, (name, child) in enumerate(parent.children()):
        assert name == names[idx]
        assert (
            type(child) is DummyBaseDevice
            if name.startswith("child")
            else type(child) is DeviceVector
        )
        assert child.parent == parent


def test_device_vector_children():
    parent = DummyDeviceGroup("root")

    device_vector_children = list(parent.dict_with_children.children())
    assert device_vector_children == [("123", parent.dict_with_children[123])]


async def test_children_of_device_have_set_names_and_get_connected(
    parent: DummyDeviceGroup,
):
    assert parent.name == "parent"
    assert parent.child1.name == "parent-child1"
    assert parent.child2.name == "parent-child2"
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
    assert parent.child2.name == "parent-child2"
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


async def test_device_lazily_connects(RE):
    class MockSignalBackendFailingFirst(MockSignalBackend):
        succeed_on_connect = False

        async def connect(self, timeout=DEFAULT_TIMEOUT):
            if self.succeed_on_connect:
                self.succeed_on_connect = False
                await super().connect(timeout=timeout)
            else:
                self.succeed_on_connect = True
                raise RuntimeError("connect fail")

    test_motor = motor.Motor("BLxxI-MO-TABLE-01:X")
    test_motor.user_setpoint._backend = MockSignalBackendFailingFirst(int)

    with pytest.raises(NotConnected, match="RuntimeError: connect fail"):
        await test_motor.connect(mock=True)

    assert (
        test_motor._connect_task
        and test_motor._connect_task.done()
        and test_motor._connect_task.exception()
    )

    RE(ensure_connected(test_motor, mock=True))

    assert (
        test_motor._connect_task
        and test_motor._connect_task.done()
        and not test_motor._connect_task.exception()
    )

    with pytest.raises(NotConnected, match="RuntimeError: connect fail"):
        RE(ensure_connected(test_motor, mock=True, force_reconnect=True))

    assert (
        test_motor._connect_task
        and test_motor._connect_task.done()
        and test_motor._connect_task.exception()
    )


async def test_device_refuses_two_connects_differing_on_mock_attribute(RE):
    motor = SimMotor("motor")
    assert not motor._connect_task
    await motor.connect(mock=False)
    assert isinstance(motor.units._backend, SoftSignalBackend)
    assert motor._connect_task
    with pytest.raises(RuntimeError) as exc:
        await motor.connect(mock=True)
    assert str(exc.value) == (
        "`connect(mock=True)` called on a `Device` where the previous connect was "
        "`mock=False`. Changing mock value between connects is not permitted."
    )


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


async def test_device_with_device_collector_refuses_to_connect_if_mock_switch():
    mock_motor = motor.Motor("NONE_EXISTENT")
    with pytest.raises(NotConnected):
        await mock_motor.connect(mock=False, timeout=0.01)
    assert (
        mock_motor._connect_task is not None
        and mock_motor._connect_task.done()
        and mock_motor._connect_task.exception()
    )
    with pytest.raises(RuntimeError) as exc:
        await mock_motor.connect(mock=True, timeout=0.01)
    assert str(exc.value) == (
        "`connect(mock=True)` called on a `Device` where the previous connect was "
        "`mock=False`. Changing mock value between connects is not permitted."
    )


async def test_no_reconnect_signals_if_not_forced():
    parent = DummyDeviceGroup("parent")

    async def inner_connect(mock, timeout, force_reconnect):
        parent.child1.connected = True

    parent.child1.connect = Mock(side_effect=inner_connect)
    await parent.connect(mock=True, timeout=0.01)
    assert parent.child1.connected
    assert parent.child1.connect.call_count == 1
    await parent.connect(mock=True, timeout=0.01)
    assert parent.child1.connected
    assert parent.child1.connect.call_count == 1

    for count in range(2, 10):
        await parent.connect(mock=True, timeout=0.01, force_reconnect=True)
        assert parent.child1.connected
        assert parent.child1.connect.call_count == count
