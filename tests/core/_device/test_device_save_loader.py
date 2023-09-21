from enum import Enum
from os import path
from typing import Dict, List

import numpy as np
import numpy.typing as npt
import pytest
import yaml
from bluesky import RunEngine

from ophyd_async.core import Device, SignalR, SignalRW
from ophyd_async.core._device.device_save_loader import save_device, walk_rw_signals
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


class DummyChildDevice(Device):
    def __init__(self):
        self.sig1: SignalRW = epics_signal_rw(str, "Value1")
        self.sig2: SignalR = epics_signal_r(str, "Value2")


class EnumTest(Enum):
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

    def sort_signal_by_phase(self, signalRWs) -> List[Dict[str, SignalRW]]:
        phase_1 = {}
        phase_2 = {}
        phase_1["child1.sig1"] = self.child1.sig1
        phase_2["child2.sig1"] = self.child2.sig1
        return [phase_1, phase_2]

    setattr(device, "sort_signal_by_phase", sort_signal_by_phase)
    return device


def test_get_signal_RWs_from_device(device):
    signalRWS = walk_rw_signals(device)
    assert list(signalRWS.keys()) == [
        "child1.sig1",
        "child2.sig1",
        "parent_sig1",
        "parent_sig3",
    ]
    assert all(isinstance(signal, SignalRW) for signal in list(signalRWS.values()))


async def test_save_device_no_phase(device, device_with_phases, tmp_path):
    RE = RunEngine()
    await device.child1.sig1.set("string")
    # Test tables PVs
    table_pv = {"VAL1": np.array([1, 1, 1, 1, 1]), "VAL2": np.array([1, 1, 1, 1, 1])}
    await device.child2.sig1.set(table_pv)

    # Test enum PVs
    await device.parent_sig3.set(EnumTest.VAL1)
    RE(save_device(device, path.join(tmp_path, "test_file"), ignore=["parent_sig1"]))

    with open(path.join(tmp_path, "test_file.yaml"), "r") as file:
        yaml_content = yaml.safe_load(file)
        assert yaml_content[0] == {
            "child1.sig1": "string",
            "child2.sig1": {
                "VAL1": [1, 1, 1, 1, 1],
                "VAL2": [1, 1, 1, 1, 1],
            },
            "parent_sig3": "val1",
        }


async def test_save_device_with_phase(device_with_phases, tmp_path):
    RE = RunEngine()
    await device_with_phases.child1.sig1.set("string")
    # mimic tables in devices
    table_pv = {"VAL1": np.array([1, 1, 1, 1, 1]), "VAL2": np.array([1, 1, 1, 1, 1])}
    await device_with_phases.child2.sig1.set(table_pv)
    RE(save_device(device_with_phases, path.join(tmp_path, "test_file")))
    with open(path.join(tmp_path, "test_file.yaml"), "r") as file:
        yaml_content = yaml.safe_load(file)
        assert yaml_content[0] == {"child1.sig1": "string"}
        assert yaml_content[1] == {"child2.sig1": table_pv}
