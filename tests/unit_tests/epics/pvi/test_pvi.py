from typing import Annotated as A
from typing import TypeVar
from unittest.mock import MagicMock

import pytest
from bluesky.protocols import HasHints, Hints

from ophyd_async.core import (
    Device,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    StandardReadable,
    init_devices,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import PviDeviceConnector


class Block1(Device, HasHints):
    device_vector_signal_x: DeviceVector[SignalX]
    device_vector_signal_rw: DeviceVector[SignalRW[float]]
    signal_x: SignalX
    signal_rw: SignalRW[int]

    @property
    def hints(self) -> Hints:
        return {}


class Block2(Device):
    device_vector: DeviceVector[Block1]
    device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block3(Device):
    device_vector: DeviceVector[Block2]
    device: Block2
    signal_device: Block1
    signal_x: SignalX
    signal_rw: SignalRW[int]


class Block4(StandardReadable):
    device_vector: DeviceVector[Block1]
    device: A[Block1, Format.CHILD]
    signal_x: SignalX
    signal_rw: SignalRW[int]


DeviceT = TypeVar("DeviceT", bound=Device)


def with_pvi_connector(
    device_type: type[DeviceT], prefix: str, name: str = ""
) -> DeviceT:
    connector = PviDeviceConnector(prefix + ":PVI")
    device = device_type(connector=connector, name=name)
    connector.create_children_from_annotations(device)
    return device


async def test_fill_pvi_entries_mock_mode():
    async with init_devices(mock=True):
        test_device = with_pvi_connector(Block3, "PREFIX:")

    # device vectors are typed
    assert isinstance(test_device.device_vector[1], Block2)
    assert isinstance(test_device.device_vector[2], Block2)

    # elements of device vectors are typed recursively
    assert test_device.device_vector[1].signal_rw._connector.backend.datatype is int
    assert isinstance(test_device.device_vector[1].device, Block1)
    assert (
        test_device.device_vector[1].device.signal_rw._connector.backend.datatype is int
    )  # type: ignore
    assert (
        test_device.device_vector[1]
        .device.device_vector_signal_rw[1]
        ._connector.backend.datatype  # type: ignore
        is float
    )

    # top level blocks are typed
    assert isinstance(test_device.signal_device, Block1)
    assert isinstance(test_device.device, Block2)

    # elements of top level blocks are typed recursively
    assert test_device.device.signal_rw._connector.backend.datatype is int  # type: ignore
    assert isinstance(test_device.device.device, Block1)
    assert test_device.device.device.signal_rw._connector.backend.datatype is int  # type: ignore

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
    assert test_device.signal_rw._connector.backend.datatype is int


async def test_device_create_children_from_annotations():
    device = with_pvi_connector(Block3, "PREFIX:")

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


async def test_device_create_children_from_annotations_with_device_vectors():
    device = with_pvi_connector(Block4, "PREFIX:", name="test_device")
    await device.connect(mock=True)

    block_1_device = device.device
    assert block_1_device in device._has_hints
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


class NoSignalType(Device):
    a: SignalRW


class NoSignalTypeInVector(Device):
    a: DeviceVector[SignalRW]


@pytest.mark.parametrize("cls", [NoSignalType, NoSignalTypeInVector])
async def test_no_type_annotation_blocks(cls):
    with pytest.raises(TypeError) as cm:
        with_pvi_connector(cls, "PREFIX:")
    assert str(cm.value) == (
        f"{cls.__name__}.a: Expected SignalX or SignalR/W/RW[type], "
        "got <class 'ophyd_async.core._signal.SignalRW'>"
    )


@pytest.mark.parametrize(
    "mock_entry, expected_signal_type",
    [
        ({"r": "read_pv"}, SignalR),
        ({"r": "read_pv", "w": "write_pv"}, SignalRW),
        ({"rw": "read_and_write_pv"}, SignalRW),
        ({"w": "write_pv"}, SignalW),
        ({"x": "triggerable_pv"}, SignalX),
        ({"invalid": "invalid_pv"}, None),
    ],
)
async def test_correctly_setting_signal_type_from_signal_details(
    mock_entry, expected_signal_type
):
    connector = PviDeviceConnector("")
    connector.filler = MagicMock()
    if not expected_signal_type:
        with pytest.raises(TypeError) as e:
            connector._fill_child("signal", mock_entry)
        assert "Can't process entry" in str(e.value)
    else:
        connector._fill_child("signal", mock_entry)
        connector.filler.fill_child_signal.assert_called_once_with(
            "signal", expected_signal_type, None
        )
