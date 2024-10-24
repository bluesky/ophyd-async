from collections.abc import Sequence
from enum import Enum
from os import path
from typing import Any
from unittest.mock import patch

import numpy as np
import numpy.typing as npt
import pytest
import yaml
from bluesky.run_engine import RunEngine
from pydantic import BaseModel, Field
from pydantic_numpy.typing import NpNDArrayFp16, NpNDArrayInt32

from ophyd_async.core import (
    Device,
    SignalR,
    SignalRW,
    all_at_once,
    get_signal_values,
    load_device,
    load_from_yaml,
    save_device,
    save_to_yaml,
    set_signal_values,
    walk_rw_signals,
)
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


class DummyChildDevice(Device):
    def __init__(self) -> None:
        self.sig1: SignalRW = epics_signal_rw(str, "Value1")
        self.sig2: SignalR = epics_signal_r(str, "Value2")


class EnumTest(str, Enum):
    VAL1 = "val1"
    VAL2 = "val2"


class DummyDeviceGroup(Device):
    def __init__(self, name: str):
        self.child1: DummyChildDevice = DummyChildDevice()
        self.child2: DummyChildDevice = DummyChildDevice()
        self.parent_sig1: SignalRW = epics_signal_rw(str, "ParentValue1")
        self.parent_sig2: SignalR = epics_signal_r(
            int, "ParentValue2"
        )  # Ensure only RW are found
        self.parent_sig3: SignalRW = epics_signal_rw(str, "ParentValue3")
        self.position: npt.NDArray[np.int32]


class MyEnum(str, Enum):
    one = "one"
    two = "two"
    three = "three"


class SomePvaPydanticModel(BaseModel):
    some_int_field: int = Field(default=1)
    some_pydantic_numpy_field_float: NpNDArrayFp16 = Field(
        default_factory=lambda: np.array([1, 2, 3])
    )
    some_pydantic_numpy_field_int: NpNDArrayInt32 = Field(
        default_factory=lambda: np.array([1, 2, 3])
    )


class DummyDeviceGroupAllTypes(Device):
    def __init__(self, name: str):
        self.pv_int: SignalRW = epics_signal_rw(int, "PV1")
        self.pv_float: SignalRW = epics_signal_rw(float, "PV2")
        self.pv_str: SignalRW = epics_signal_rw(str, "PV2")
        self.pv_enum_str: SignalRW = epics_signal_rw(MyEnum, "PV3")
        self.pv_enum: SignalRW = epics_signal_rw(MyEnum, "PV4")
        self.pv_array_int8 = epics_signal_rw(npt.NDArray[np.int8], "PV5")
        self.pv_array_uint8 = epics_signal_rw(npt.NDArray[np.uint8], "PV6")
        self.pv_array_int16 = epics_signal_rw(npt.NDArray[np.int16], "PV7")
        self.pv_array_uint16 = epics_signal_rw(npt.NDArray[np.uint16], "PV8")
        self.pv_array_int32 = epics_signal_rw(npt.NDArray[np.int32], "PV9")
        self.pv_array_uint32 = epics_signal_rw(npt.NDArray[np.uint32], "PV10")
        self.pv_array_int64 = epics_signal_rw(npt.NDArray[np.int64], "PV11")
        self.pv_array_uint64 = epics_signal_rw(npt.NDArray[np.uint64], "PV12")
        self.pv_array_float32 = epics_signal_rw(npt.NDArray[np.float32], "PV13")
        self.pv_array_float64 = epics_signal_rw(npt.NDArray[np.float64], "PV14")
        self.pv_array_npstr = epics_signal_rw(npt.NDArray[np.str_], "PV15")
        self.pv_array_str = epics_signal_rw(Sequence[str], "PV16")
        self.pv_protocol_device_abstraction = epics_signal_rw(
            SomePvaPydanticModel, "pva://PV17"
        )


@pytest.fixture
async def device() -> DummyDeviceGroup:
    device = DummyDeviceGroup("parent")
    await device.connect(mock=True)
    return device


@pytest.fixture
async def device_all_types() -> DummyDeviceGroupAllTypes:
    device = DummyDeviceGroupAllTypes("parent")
    await device.connect(mock=True)
    return device


# Dummy function to check different phases save properly
def sort_signal_by_phase(values: dict[str, Any]) -> list[dict[str, Any]]:
    phase_1 = {"child1.sig1": values["child1.sig1"]}
    phase_2 = {"child2.sig1": values["child2.sig1"]}
    return [phase_1, phase_2]


async def test_enum_yaml_formatting(tmp_path):
    enums = [EnumTest.VAL1, EnumTest.VAL2]
    save_to_yaml(enums, path.join(tmp_path, "test_file.yaml"))
    with open(path.join(tmp_path, "test_file.yaml")) as file:
        saved_enums = yaml.load(file, yaml.Loader)
    # check that save/load reduces from enum to str
    assert all(isinstance(value, str) for value in saved_enums)
    # check values of enums same
    assert saved_enums == enums


async def test_save_device_all_types(RE: RunEngine, device_all_types, tmp_path):
    # Populate fake device with PV's...
    await device_all_types.pv_int.set(1)
    await device_all_types.pv_float.set(1.234)
    await device_all_types.pv_str.set("test_string")
    await device_all_types.pv_enum_str.set("two")
    await device_all_types.pv_enum.set(MyEnum.two)
    for pv, dtype in {
        device_all_types.pv_array_int8: np.int8,
        device_all_types.pv_array_uint8: np.uint8,
        device_all_types.pv_array_int16: np.int16,
        device_all_types.pv_array_uint16: np.uint16,
        device_all_types.pv_array_int32: np.int32,
        device_all_types.pv_array_uint32: np.uint32,
        device_all_types.pv_array_int64: np.int64,
        device_all_types.pv_array_uint64: np.uint64,
    }.items():
        await pv.set(
            np.array(
                [np.iinfo(dtype).min, np.iinfo(dtype).max, 0, 1, 2, 3, 4], dtype=dtype
            )
        )
    for pv, dtype in {
        device_all_types.pv_array_float32: np.float32,
        device_all_types.pv_array_float64: np.float64,
    }.items():
        finfo = np.finfo(dtype)
        data = np.array(
            [
                finfo.min,
                finfo.max,
                finfo.smallest_normal,
                finfo.smallest_subnormal,
                0,
                1.234,
                2.34e5,
                3.45e-6,
            ],
            dtype=dtype,
        )

        await pv.set(data)
    await device_all_types.pv_array_npstr.set(
        np.array(["one", "two", "three"], dtype=np.str_),
    )
    await device_all_types.pv_array_str.set(
        ["one", "two", "three"],
    )
    await device_all_types.pv_protocol_device_abstraction.set(SomePvaPydanticModel())

    # Create save plan from utility functions
    def save_my_device():
        signalRWs = walk_rw_signals(device_all_types)
        values = yield from get_signal_values(signalRWs)

        save_to_yaml([values], path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    actual_file_path = path.join(tmp_path, "test_file.yaml")
    with open(actual_file_path) as actual_file:
        with open("tests/test_data/test_yaml_save.yml") as expected_file:
            assert actual_file.read() == expected_file.read()


async def test_save_device(RE: RunEngine, device, tmp_path):
    # Populate fake device with PV's...
    await device.child1.sig1.set("test_string")
    # Test tables PVs
    table_pv = {"VAL1": np.array([1, 1, 1, 1, 1]), "VAL2": np.array([1, 1, 1, 1, 1])}
    await device.child2.sig1.set(table_pv)

    # Test enum PVs
    await device.parent_sig3.set(EnumTest.VAL1)

    # Create save plan from utility functions
    def save_my_device():
        signalRWs = walk_rw_signals(device)

        assert list(signalRWs.keys()) == [
            "child1.sig1",
            "child2.sig1",
            "parent_sig1",
            "parent_sig3",
        ]
        assert all(isinstance(signal, SignalRW) for signal in list(signalRWs.values()))

        values = yield from get_signal_values(signalRWs, ignore=["parent_sig1"])

        assert values == {
            "child1.sig1": "test_string",
            "child2.sig1": table_pv,
            "parent_sig3": "val1",
            "parent_sig1": None,
        }

        save_to_yaml([values], path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    with open(path.join(tmp_path, "test_file.yaml")) as file:
        yaml_content = yaml.load(file, yaml.Loader)[0]
        assert len(yaml_content) == 4
        assert yaml_content["child1.sig1"] == "test_string"
        assert np.array_equal(
            yaml_content["child2.sig1"]["VAL1"], np.array([1, 1, 1, 1, 1])
        )
        assert np.array_equal(
            yaml_content["child2.sig1"]["VAL2"], np.array([1, 1, 1, 1, 1])
        )
        assert yaml_content["parent_sig3"] == "val1"
        assert yaml_content["parent_sig1"] is None


async def test_yaml_formatting(RE: RunEngine, device, tmp_path):
    file_path = path.join(tmp_path, "test_file.yaml")
    await device.child1.sig1.set("test_string")
    table_pv = {"VAL1": np.array([1, 2, 3, 4, 5]), "VAL2": np.array([6, 7, 8, 9, 10])}
    await device.child2.sig1.set(table_pv)
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    with open(file_path) as file:
        expected = """\
- child1.sig1: test_string
- child2.sig1:
    VAL1: [1, 2, 3, 4, 5]
    VAL2: [6, 7, 8, 9, 10]
"""
        assert file.read() == expected


async def test_load_from_yaml(RE: RunEngine, device, tmp_path):
    file_path = path.join(tmp_path, "test_file.yaml")

    array = np.array([1, 1, 1, 1, 1])
    await device.child1.sig1.set("initial_string")
    await device.child2.sig1.set(array)
    await device.parent_sig1.set(None)
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    values = load_from_yaml(file_path)
    assert values[0]["child1.sig1"] == "initial_string"
    assert np.array_equal(values[1]["child2.sig1"], array)


async def test_set_signal_values_restores_value(RE: RunEngine, device, tmp_path):
    file_path = path.join(tmp_path, "test_file.yaml")

    await device.child1.sig1.set("initial_string")
    await device.child2.sig1.set(np.array([1, 1, 1, 1, 1]))
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    await device.child1.sig1.set("changed_string")
    await device.child2.sig1.set(np.array([2, 2, 2, 2, 2]))
    string_value = await device.child1.sig1.get_value()
    array_value = await device.child2.sig1.get_value()
    assert string_value == "changed_string"
    assert np.array_equal(array_value, np.array([2, 2, 2, 2, 2]))

    values = load_from_yaml(file_path)
    signals_to_set = walk_rw_signals(device)

    RE(set_signal_values(signals_to_set, values))

    string_value = await device.child1.sig1.get_value()
    array_value = await device.child2.sig1.get_value()
    assert string_value == "initial_string"
    assert np.array_equal(array_value, np.array([1, 1, 1, 1, 1]))


@patch("ophyd_async.core._device_save_loader.load_from_yaml")
@patch("ophyd_async.core._device_save_loader.walk_rw_signals")
@patch("ophyd_async.core._device_save_loader.set_signal_values")
async def test_load_device(
    mock_set_signal_values, mock_walk_rw_signals, mock_load_from_yaml, device
):
    RE = RunEngine()
    RE(load_device(device, "path"))
    mock_load_from_yaml.assert_called_once()
    mock_walk_rw_signals.assert_called_once()
    mock_set_signal_values.assert_called_once()


async def test_set_signal_values_skips_ignored_values(device):
    RE = RunEngine()
    array = np.array([1, 1, 1, 1, 1])

    await device.child1.sig1.set("initial_string")
    await device.child2.sig1.set(array)
    await device.parent_sig1.set(None)

    signals_of_device = walk_rw_signals(device)
    values_to_set = [{"child1.sig1": None, "child2.sig1": np.array([2, 3, 4])}]

    RE(set_signal_values(signals_of_device, values_to_set))

    assert np.all(await device.child2.sig1.get_value() == np.array([2, 3, 4]))
    assert await device.child1.sig1.get_value() == "initial_string"


def test_all_at_once_sorter():
    assert all_at_once({"child1.sig1": 0}) == [{"child1.sig1": 0}]
