import asyncio
import traceback

import pytest

from ophyd_async.core.devices import Device, DeviceVector, get_device_children
from ophyd_async.core.devices.device_collector import DeviceCollector
from ophyd_async.core.utils import wait_for_connection


class DummyBaseDevice(Device):
    def __init__(self) -> None:
        self.connected = False

    async def connect(self, sim=False):
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


def test_get_device_children(parent: DummyDeviceGroup):
    names = ["child1", "child2", "dict_with_children"]
    for idx, (name, child) in enumerate(get_device_children(parent)):
        assert name == names[idx]
        assert (
            type(child) is DummyBaseDevice
            if name.startswith("child")
            else type(child) is DeviceVector
        )


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
    async with DeviceCollector(sim=True):
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

        async def connect(self, sim=False):
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

    with pytest.raises(ValueError) as e:
        await wait_for_connection(**failing_coros)
        assert traceback.extract_tb(e.__traceback__)[-1].name == "failing_coroutine"
