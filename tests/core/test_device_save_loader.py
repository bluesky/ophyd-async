from os import path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
import yaml
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    Array1D,
    Device,
    SignalRW,
    StrictEnum,
    Table,
    all_at_once,
    get_signal_values,
    load_device,
    load_from_yaml,
    save_device,
    save_to_yaml,
    set_signal_values,
    walk_rw_signals,
)
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw
from ophyd_async.epics.testing import ExampleEnum, ExampleTable, PvaDevice


class EnumTest(StrictEnum):
    VAL1 = "val1"
    VAL2 = "val2"


class DummyChildDevice(Device):
    def __init__(self) -> None:
        self.str_sig = epics_signal_rw(str, "StrSignal")
        super().__init__()


class DummyDeviceGroup(Device):
    def __init__(self, name: str):
        self.child1 = DummyChildDevice()
        self.child2 = DummyChildDevice()
        self.str_sig = epics_signal_rw(str, "ParentValue1")
        self.parent_sig2 = epics_signal_r(
            int, "ParentValue2"
        )  # Ensure only RW are found
        self.table_sig = epics_signal_rw(Table, "TableSignal")
        self.array_sig = epics_signal_rw(Array1D[np.uint32], "ArraySignal")
        self.enum_sig = epics_signal_rw(EnumTest, "EnumSignal")
        super().__init__(name)


@pytest.fixture
async def device() -> DummyDeviceGroup:
    device = DummyDeviceGroup("parent")
    await device.connect(mock=True)
    return device


@pytest.fixture
async def device_all_types() -> PvaDevice:
    device = PvaDevice("parent")
    await device.connect(mock=True)
    return device


# Dummy function to check different phases save properly
def sort_signal_by_phase(values: dict[str, Any]) -> list[dict[str, Any]]:
    phase_1 = {"child1.str_sig": values["child1.str_sig"]}
    phase_2 = {"child2.str_sig": values["child2.str_sig"]}
    phase_3 = {
        key: value
        for key, value in values.items()
        if key not in phase_1 and key not in phase_2
    }
    return [phase_1, phase_2, phase_3]


async def test_enum_yaml_formatting(tmp_path):
    enums = [EnumTest.VAL1, EnumTest.VAL2]
    save_to_yaml(enums, path.join(tmp_path, "test_file.yaml"))
    with open(path.join(tmp_path, "test_file.yaml")) as file:
        saved_enums = yaml.load(file, yaml.Loader)
    # check that save/load reduces from enum to str
    assert all(isinstance(value, str) for value in saved_enums)
    # check values of enums same
    assert saved_enums == enums


async def test_save_device_all_types(
    RE: RunEngine, device_all_types: PvaDevice, tmp_path
):
    # Populate fake device with PV's...
    await device_all_types.my_int.set(1)
    await device_all_types.my_float.set(1.234)
    await device_all_types.my_str.set("test_string")
    await device_all_types.enum.set(ExampleEnum.b)
    await device_all_types.enum2.set("Bbb")
    for pv, dtype in {
        device_all_types.int8a: np.int8,
        device_all_types.uint8a: np.uint8,
        device_all_types.int16a: np.int16,
        device_all_types.uint16a: np.uint16,
        device_all_types.int32a: np.int32,
        device_all_types.uint32a: np.uint32,
        device_all_types.int64a: np.int64,
        device_all_types.uint64a: np.uint64,
    }.items():
        await pv.set(
            np.array(
                [np.iinfo(dtype).min, np.iinfo(dtype).max, 0, 1, 2, 3, 4], dtype=dtype
            )
        )
    for pv, dtype in {
        device_all_types.float32a: np.float32,
        device_all_types.float64a: np.float64,
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
    await device_all_types.stra.set(
        ["one", "two", "three"],
    )
    await device_all_types.table.set(
        ExampleTable(
            bool=np.array([False, False, True, True], np.bool_),
            int=np.array([1, 8, -9, 32], np.int32),
            float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
            str=["Hello", "World", "Foo", "Bar"],
            enum=[ExampleEnum.a, ExampleEnum.b, ExampleEnum.a, ExampleEnum.c],
        )
    )

    # Create save plan from utility functions
    def save_my_device():
        signalRWs = walk_rw_signals(device_all_types)
        values = yield from get_signal_values(signalRWs)

        save_to_yaml([values], path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    actual_file_path = path.join(tmp_path, "test_file.yaml")
    with open(actual_file_path) as actual_file:
        with open("tests/test_data/test_yaml_save.yml") as expected_file:
            assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)


async def test_save_device(RE: RunEngine, device: DummyDeviceGroup, tmp_path):
    # Populate fake device with PV's...
    await device.child1.str_sig.set("test_string")
    # Test tables PVs
    table_pv = {"VAL1": np.array([1, 1, 1, 1, 1]), "VAL2": np.array([1, 1, 1, 1, 1])}
    array_pv = np.array([2, 2, 2, 2, 2])
    await device.array_sig.set(array_pv)
    await device.table_sig.set(table_pv)
    await device.enum_sig.set(EnumTest.VAL2)

    # Create save plan from utility functions
    def save_my_device():
        signalRWs = walk_rw_signals(device)

        assert list(signalRWs.keys()) == [
            "child1.str_sig",
            "child2.str_sig",
            "str_sig",
            "table_sig",
            "array_sig",
            "enum_sig",
        ]
        assert all(isinstance(signal, SignalRW) for signal in list(signalRWs.values()))

        values = yield from get_signal_values(signalRWs, ignore=["str_sig"])
        assert np.array_equal(values["array_sig"], array_pv)
        assert values["enum_sig"] == "val2"
        assert values["table_sig"] == Table(**table_pv)
        assert values["str_sig"] is None
        assert values["child1.str_sig"] == "test_string"
        assert values["child2.str_sig"] == ""

        save_to_yaml([values], path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    with open(path.join(tmp_path, "test_file.yaml")) as file:
        yaml_content = yaml.load(file, yaml.Loader)[0]
        assert yaml_content["child1.str_sig"] == "test_string"
        assert yaml_content["child2.str_sig"] == ""
        assert np.array_equal(yaml_content["table_sig"]["VAL1"], table_pv["VAL1"])
        assert np.array_equal(yaml_content["table_sig"]["VAL2"], table_pv["VAL2"])
        assert np.array_equal(yaml_content["array_sig"], array_pv)
        assert yaml_content["enum_sig"] == "val2"
        assert yaml_content["str_sig"] is None


async def test_yaml_formatting(RE: RunEngine, device: DummyDeviceGroup, tmp_path):
    file_path = path.join(tmp_path, "test_file.yaml")
    await device.child1.str_sig.set("test_string")
    table = {"VAL1": np.array([1, 2, 3, 4, 5]), "VAL2": np.array([6, 7, 8, 9, 10])}
    await device.array_sig.set(np.array([11, 12, 13, 14, 15]))
    await device.table_sig.set(table)
    await device.enum_sig.set(EnumTest.VAL2)
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    with open(file_path) as file:
        expected = """\
- child1.str_sig: test_string
- child2.str_sig: ''
- array_sig: [11, 12, 13, 14, 15]
  enum_sig: val2
  str_sig: ''
  table_sig:
    VAL1: [1, 2, 3, 4, 5]
    VAL2: [6, 7, 8, 9, 10]
"""
        # assert False, file.read()
        assert file.read() == expected


async def test_load_from_yaml(RE: RunEngine, device: DummyDeviceGroup, tmp_path):
    file_path = path.join(tmp_path, "test_file.yaml")

    array = np.array([1, 1, 1, 1, 1])
    table = {"VAL1": np.array([1, 2, 3, 4, 5]), "VAL2": np.array([6, 7, 8, 9, 10])}
    await device.child1.str_sig.set("initial_string")
    await device.array_sig.set(array)
    await device.str_sig.set(None)
    await device.enum_sig.set(EnumTest.VAL2)
    await device.table_sig.set(table)
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    values = load_from_yaml(file_path)
    assert values[0]["child1.str_sig"] == "initial_string"
    assert values[1]["child2.str_sig"] == ""
    assert values[2]["str_sig"] == ""
    assert values[2]["enum_sig"] == "val2"
    assert np.array_equal(values[2]["array_sig"], array)
    assert np.array_equal(values[2]["table_sig"]["VAL1"], table["VAL1"])
    assert np.array_equal(values[2]["table_sig"]["VAL2"], table["VAL2"])


async def test_set_signal_values_restores_value(
    RE: RunEngine, device: DummyDeviceGroup, tmp_path
):
    file_path = path.join(tmp_path, "test_file.yaml")

    await device.str_sig.set("initial_string")
    await device.array_sig.set(np.array([1, 1, 1, 1, 1]))
    RE(save_device(device, file_path, sorter=sort_signal_by_phase))

    await device.str_sig.set("changed_string")
    await device.array_sig.set(np.array([2, 2, 2, 2, 2]))
    string_value = await device.str_sig.get_value()
    array_value = await device.array_sig.get_value()
    assert string_value == "changed_string"
    assert np.array_equal(array_value, np.array([2, 2, 2, 2, 2]))

    values = load_from_yaml(file_path)
    signals_to_set = walk_rw_signals(device)

    RE(set_signal_values(signals_to_set, values))

    string_value = await device.str_sig.get_value()
    array_value = await device.array_sig.get_value()
    assert string_value == "initial_string"
    assert np.array_equal(array_value, np.array([1, 1, 1, 1, 1]))


@patch("ophyd_async.core._device_save_loader.load_from_yaml")
@patch("ophyd_async.core._device_save_loader.walk_rw_signals")
@patch("ophyd_async.core._device_save_loader.set_signal_values")
async def test_load_device(
    mock_set_signal_values,
    mock_walk_rw_signals,
    mock_load_from_yaml,
    device: DummyDeviceGroup,
):
    RE = RunEngine()
    RE(load_device(device, "path"))
    mock_load_from_yaml.assert_called_once()
    mock_walk_rw_signals.assert_called_once()
    mock_set_signal_values.assert_called_once()


async def test_set_signal_values_skips_ignored_values(device: DummyDeviceGroup):
    RE = RunEngine()
    array = np.array([1, 1, 1, 1, 1])

    await device.child1.str_sig.set("initial_string")
    await device.array_sig.set(array)
    await device.str_sig.set(None)

    signals_of_device = walk_rw_signals(device)
    values_to_set = [{"child1.str_sig": None, "array_sig": np.array([2, 3, 4])}]

    RE(set_signal_values(signals_of_device, values_to_set))

    assert np.all(await device.array_sig.get_value() == np.array([2, 3, 4]))
    assert await device.child1.str_sig.get_value() == "initial_string"


def test_all_at_once_sorter():
    assert all_at_once({"child1.str_sig": 0}) == [{"child1.str_sig": 0}]
