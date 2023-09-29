from enum import Enum
from os import path
from typing import Any, Dict, List

import numpy as np
import numpy.typing as npt
import pytest
import yaml
from bluesky import RunEngine

from ophyd_async.core import Device, SignalR, SignalRW
from ophyd_async.core._device.device_save_loader import (
    get_signal_values,
    ndarray_constructor,
    save_to_yaml,
    walk_rw_signals,
)
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


class DummyChildDevice(Device):
    def __init__(self):
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


@pytest.fixture
async def device() -> DummyDeviceGroup:
    device = DummyDeviceGroup("parent")
    await device.connect(sim=True)
    return device


@pytest.fixture
async def device_with_phases() -> DummyDeviceGroup:
    device = DummyDeviceGroup("parent")
    await device.connect(sim=True)

    # Dummy function to check different phases save properly
    def sort_signal_by_phase(self, values: Dict[str, Any]) -> List[Dict[str, Any]]:
        phase_1 = {"child1.sig1": values["child1.sig1"]}
        phase_2 = {"child2.sig1": values["child2.sig1"]}
        return [phase_1, phase_2]

    setattr(device, "sort_signal_by_phase", sort_signal_by_phase)
    return device


async def test_save_device_no_phase(device, tmp_path):
    RE = RunEngine()

    # Populate fake device with PV's...
    await device.child1.sig1.set("string")
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
            "child1.sig1": "string",
            "child2.sig1": table_pv,
            "parent_sig3": EnumTest.VAL1,
            "parent_sig1": None,
        }

        save_to_yaml(values, path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    yaml.add_constructor("tag:!numpy.ndarray", ndarray_constructor)

    with open(path.join(tmp_path, "test_file.yaml"), "r") as file:
        yaml_content = yaml.load(file, yaml.Loader)[0]
        assert len(yaml_content) == 4
        assert yaml_content["child1.sig1"] == "string"
        assert np.array_equal(
            yaml_content["child2.sig1"]["VAL1"], np.array([1, 1, 1, 1, 1])
        )
        assert np.array_equal(
            yaml_content["child2.sig1"]["VAL2"], np.array([1, 1, 1, 1, 1])
        )
        assert yaml_content["parent_sig3"] == "val1"
        assert yaml_content["parent_sig1"] is None


async def test_save_device_with_phase(device_with_phases, tmp_path):
    RE = RunEngine()
    await device_with_phases.child1.sig1.set("string")
    table_pv = {"VAL1": np.array([1, 1, 1, 1, 1]), "VAL2": np.array([1, 1, 1, 1, 1])}
    await device_with_phases.child2.sig1.set(table_pv)

    # Create save plan from utility functions
    def save_my_device():
        signalRWs = walk_rw_signals(device_with_phases)
        values = yield from get_signal_values(signalRWs)
        phases = device_with_phases.sort_signal_by_phase(device_with_phases, values)
        save_to_yaml(phases, path.join(tmp_path, "test_file.yaml"))

    RE(save_my_device())

    yaml.add_constructor("tag:!numpy.ndarray", ndarray_constructor)

    with open(path.join(tmp_path, "test_file.yaml"), "r") as file:
        yaml_content = yaml.load(file, yaml.Loader)
        assert yaml_content[0] == {"child1.sig1": "string"}
        assert np.array_equal(
            yaml_content[1]["child2.sig1"]["VAL1"], np.array([1, 1, 1, 1, 1])
        )
        assert np.array_equal(
            yaml_content[1]["child2.sig1"]["VAL2"], np.array([1, 1, 1, 1, 1])
        )
