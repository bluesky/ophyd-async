import pytest

from ophyd_async.core import (
    Device,
    DeviceBackend,
    DeviceCollector,
    DeviceVector,
    SignalRW,
    SignalX,
)
from ophyd_async.epics.pvi import PviDeviceBackend


class PviDevice(Device):
    def __init__(
        self, prefix: str = "", name: str = "", backend: DeviceBackend | None = None
    ):
        if backend is None:
            backend = PviDeviceBackend(type(self), prefix + "PVI")
        super().__init__(name=name, backend=backend)


class Block1(PviDevice):
    device_vector_signal_x: DeviceVector[SignalX]
    device_vector_signal_rw: DeviceVector[SignalRW[float]]
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block2(PviDevice):
    device_vector: DeviceVector[Block1]
    device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block3(PviDevice):
    device_vector: DeviceVector[Block2]
    device: Block2
    signal_device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


async def test_fill_pvi_entries_mock_mode():
    async with DeviceCollector(mock=True):
        test_device = Block3("PREFIX:")

    # device vectors are typed
    assert isinstance(test_device.device_vector[1], Block2)
    assert isinstance(test_device.device_vector[2], Block2)

    # elements of device vectors are typed recursively
    assert test_device.device_vector[1].signal_rw._backend.datatype is int
    assert isinstance(test_device.device_vector[1].device, Block1)
    assert test_device.device_vector[1].device.signal_rw._backend.datatype is int  # type: ignore
    assert (
        test_device.device_vector[1].device.device_vector_signal_rw[1]._backend.datatype  # type: ignore
        is float
    )

    # top level blocks are typed
    assert isinstance(test_device.signal_device, Block1)
    assert isinstance(test_device.device, Block2)

    # elements of top level blocks are typed recursively
    assert test_device.device.signal_rw._backend.datatype is int  # type: ignore
    assert isinstance(test_device.device.device, Block1)
    assert test_device.device.device.signal_rw._backend.datatype is int  # type: ignore

    assert test_device.signal_rw.parent == test_device
    assert test_device.device_vector.parent == test_device
    assert test_device.device_vector[1].parent == test_device.device_vector
    assert test_device.device_vector[1].device.parent == test_device.device_vector[1]

    assert test_device.name == "test_device"
    assert test_device.device_vector.name == "test_device-device_vector"
    assert test_device.device_vector[1].name == "test_device-device_vector-1"
    assert (
        test_device.device_vector[1].device.name == "test_device-device_vector-1-device"
    )

    # top level signals are typed
    assert test_device.signal_rw._backend.datatype is int


async def test_device_create_children_from_annotations():
    device = Block3("PREFIX:")

    block_2_device = device.device
    block_1_device = device.device.device
    top_block_1_device = device.signal_device

    # The create_children_from_annotations has made blocks all the way down
    assert isinstance(block_2_device, Block2)
    assert isinstance(block_1_device, Block1)
    assert isinstance(top_block_1_device, Block1)
    assert hasattr(device, "signal_x")
    assert hasattr(device, "signal_rw")
    assert hasattr(top_block_1_device, "signal_rw")

    await device.connect(mock=True)

    # The memory addresses have not changed
    assert device.device is block_2_device
    assert device.device.device is block_1_device
    assert device.signal_device is top_block_1_device


@pytest.fixture
def pvi_test_device_with_device_vectors_t():
    """A fixture since pytest discourages init in test case classes"""

    class TestBlock(PviDevice):
        device_vector: DeviceVector[Block1]
        device: Block1
        signal_x: SignalX
        signal_rw: SignalRW[int]

    yield TestBlock


async def test_device_create_children_from_annotations_with_device_vectors(
    pvi_test_device_with_device_vectors_t,
):
    device = pvi_test_device_with_device_vectors_t("PREFIX:", name="test_device")
    await device.connect(mock=True)

    block_1_device = device.device
    block_2_device_vector = device.device_vector

    assert device.device_vector[1].name == "test_device-device_vector-1"
    assert device.device_vector[2].name == "test_device-device_vector-2"

    # create_children_from_annotiations should have made DeviceVectors
    # and an optional Block, but no signals
    assert hasattr(device, "device_vector")
    assert hasattr(device, "signal_rw")
    assert isinstance(block_2_device_vector, DeviceVector)
    assert isinstance(block_2_device_vector[1], Block1)
    assert len(device.device_vector) == 2
    assert isinstance(block_1_device, Block1)

    # The memory addresses have not changed
    assert device.device is block_1_device
    assert device.device_vector is block_2_device_vector
