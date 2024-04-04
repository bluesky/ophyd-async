from typing import Optional

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    DeviceVector,
    SignalRW,
    SignalX,
)
from ophyd_async.epics.pvi import fill_pvi_entries, pre_initialize_blocks


class Block1(Device):
    device_vector_signal_x: DeviceVector[SignalX]
    device_vector_signal_rw: DeviceVector[SignalRW[float]]
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block2(Device):
    device_vector: DeviceVector[Block1]
    device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block3(Device):
    device_vector: Optional[DeviceVector[Block2]]
    device: Block2
    signal_device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


@pytest.fixture
def pvi_test_device_t():
    """A fixture since pytest discourages init in test case classes"""

    class TestDevice(Block3, Device):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(
            self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
        ) -> None:
            await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)

            await super().connect(sim)

    yield TestDevice


async def test_fill_pvi_entries_sim_mode(pvi_test_device_t):
    async with DeviceCollector(sim=True):
        test_device = pvi_test_device_t("PREFIX:")

    # device vectors are typed
    assert isinstance(test_device.device_vector[1], Block2)
    assert isinstance(test_device.device_vector[2], Block2)

    # elements of device vectors are typed recursively
    assert test_device.device_vector[1].signal_rw._backend.datatype is int
    assert isinstance(test_device.device_vector[1].device, Block1)
    assert test_device.device_vector[1].device.signal_rw._backend.datatype is int
    assert (
        test_device.device_vector[1].device.device_vector_signal_rw[1]._backend.datatype
        is float
    )

    # top level blocks are typed
    assert isinstance(test_device.signal_device, Block1)
    assert isinstance(test_device.device, Block2)

    # elements of top level blocks are typed recursively
    assert test_device.device.signal_rw._backend.datatype is int
    assert isinstance(test_device.device.device, Block1)
    assert test_device.device.device.signal_rw._backend.datatype is int

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


@pytest.fixture
def pvi_test_device_pre_initialize_blocks_t():
    """A fixture since pytest discourages init in test case classes"""

    class TestDevice(Block3, Device):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)
            pre_initialize_blocks(self)

        async def connect(
            self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
        ) -> None:
            await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)

            await super().connect(sim)

    yield TestDevice


async def test_device_pre_initialize_blocks(pvi_test_device_pre_initialize_blocks_t):
    device = pvi_test_device_pre_initialize_blocks_t("PREFIX:")

    block_2_device = device.device
    block_1_device = device.device.device
    top_block_1_device = device.signal_device

    # The pre_initialize_blocks has only made blocks,
    # not signals or device vectors
    assert isinstance(block_2_device, Block2)
    assert isinstance(block_1_device, Block1)
    assert isinstance(top_block_1_device, Block1)
    assert not hasattr(device, "signal_x")
    assert not hasattr(device, "signal_rw")
    assert not hasattr(top_block_1_device, "signal_rw")

    await device.connect(sim=True)

    # The memory addresses have not changed
    assert device.device is block_2_device
    assert device.device.device is block_1_device
    assert device.signal_device is top_block_1_device
