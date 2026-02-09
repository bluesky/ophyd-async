from __future__ import annotations

import asyncio
import re

from pydantic import Field

from ophyd_async.core import (
    ConfinedModel,
    Device,
    DeviceConnector,
    DeviceFiller,
    LazyMock,
    Signal,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    gather_dict,
)

from ._epics_connector import fill_backend_with_prefix
from ._signal import PvaSignalBackend, pvget_with_timeout

Entry = dict[str, str]


class PviDeviceConnector(DeviceConnector):
    """Connect to PVI structure served over PVA.

    At init, fill in all the type hinted signals. At connection check their
    types and fill in any extra signals.

    :param prefix:
        The PV prefix of the device, "PVI" will be appended to it to get the PVI
        PV.
    :param error_hint:
        If given, this will be appended to the error message if any of they type
        hinted Signals are not present.
    """

    mock_device_vector_len: int = 2
    pvi_tree: PviTree | None = None

    def __init__(self, prefix: str = "", error_hint: str = "") -> None:
        # TODO: what happens if we get a leading "pva://" here?
        self.prefix = prefix
        self.pvi_pv = prefix + "PVI"
        self.error_hint = error_hint

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            self.filler = DeviceFiller(
                device=device,
                signal_backend_factory=PvaSignalBackend,
                device_connector_factory=PviDeviceConnector,
            )
            # Devices will be created with unfilled PviDeviceConnectors
            list(self.filler.create_devices_from_annotations(filled=False))
            # Signals can be filled in with EpicsSignalSuffix and checked at runtime
            for backend, annotations in self.filler.create_signals_from_annotations(
                filled=False
            ):
                fill_backend_with_prefix(self.prefix, backend, annotations)
            self.filler.check_created()

    async def connect_mock(self, device: Device, mock: LazyMock):
        self.filler.create_device_vector_entries_to_mock(self.mock_device_vector_len)
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_mock(device, mock)

    async def connect_real(
        self, device: Device, timeout: float, force_reconnect: bool
    ) -> None:
        if not self.pvi_tree:
            # Top-level device, so discover PVI tree
            self.pvi_tree = await PviTree.build_device_tree(
                name=device.name, pvi_pv=self.pvi_pv, timeout=10
            )
            print(self.pvi_tree)
        # Fill all signals
        for signal_name, signal_details in self.pvi_tree.signals.items():
            backend = self.filler.fill_child_signal(
                signal_name, signal_details.signal_type, None
            )
            backend.read_pv = signal_details.read_pv
            backend.write_pv = signal_details.write_pv
        # Fill all sub devices
        for device_name, device_sub_tree in self.pvi_tree.sub_devices.items():
            if device_sub_tree.vector_children:
                # This is a DeviceVector
                for vector_child in device_sub_tree.vector_children:
                    connector = self.filler.fill_child_device(
                        device_name, vector_index=int(vector_child.root_node)
                    )
                    connector.pvi_tree = vector_child
                    connector.pvi_pv = vector_child.pvi_pv
            else:
                # This is a Device
                connector = self.filler.fill_child_device(device_name)
                connector.pvi_tree = device_sub_tree
                connector.pvi_pv = device_sub_tree.pvi_pv

        # Check that all the requested children have been filled
        suffix = f"\n{self.error_hint}" if self.error_hint else ""
        self.filler.check_filled(f"{self.pvi_pv}: {self.pvi_tree}{suffix}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_real(device, timeout, force_reconnect)


class SignalDetails(ConfinedModel):
    """Representation of a Signal to be constructed."""

    signal_type: type[Signal]
    read_pv: str
    write_pv: str

    @classmethod
    def from_entry(cls, entry: Entry):
        match entry:
            case {"r": read_pv, "w": write_pv}:
                return cls(signal_type=SignalRW, read_pv=read_pv, write_pv=write_pv)

            case {"rw": pv}:
                return cls(signal_type=SignalRW, read_pv=pv, write_pv=pv)

            case {"r": read_pv}:
                return cls(signal_type=SignalR, read_pv=read_pv, write_pv=read_pv)

            case {"w": write_pv}:
                return cls(signal_type=SignalW, read_pv=write_pv, write_pv=write_pv)

            case {"x": execute_pv}:
                return cls(signal_type=SignalX, read_pv=execute_pv, write_pv=execute_pv)

            case _:
                raise TypeError(f"Can't process entry {entry}")


class PviTree(ConfinedModel):
    """Representation of a PVI structure of devices and signals in a PVI query.

    Example 1: A device with sub-devices and signals
    --------------------------------------
    For a PVI structure such as:

    ```json
    {
        "bit": {"d": "TEST-PANDA:Bits:PVI"},
        "calc": {"d": "TEST-PANDA:Calc:PVI"},
        "a": {"rw": "TEST-PANDA:Bits:A"}
    }
    ```

    From "TEST-PANDA:PVI", This would be represented as:

    ```python
    PviTree(
        pvi_pv="TEST-PANDA:PVI",
        root_node="panda",
        signals={
            "a": SignalDetails(
                signal_type=SignalRW,
                read_pv="TEST-PANDA:Bits:A",
                write_pv="TEST-PANDA:Bits:A")
        },
        sub_devices={
            "bit": PviTree(...),
            "calc": PviTree(...)
        },
        vector_children=[]
    )
    ```

    Example 2: A device with vector children
    -----------------------------------------
    If an entry like `"calc"` is a **DeviceVector**
    (e.g., mirroring a fastCS controller vector), the PVI entries will look like this:

    ```json
    {
        "__1": {"d": "TEST-PANDA:Calc:2:PVI"},
        "__2": {"d": "TEST-PANDA:Calc:1:PVI"}
    }
    ```

    This would be represented as:

    ```python
    PviTree(
        pvi_pv="TEST-PANDA:Calc:PVI",
        root_node="calc",
        signals={},
        sub_devices={},
        vector_children=[
            PviTree(pvi_pv="TEST-PANDA:Calc:2:PVI", root_node="1", signals={}, ...),
            PviTree(pvi_pv="TEST-PANDA:Calc:1:PVI", root_node="2", signals={}, ...)
        ]
    )
    ```

    :param pvi_pv:
        The PVI PV of the device.

    :param root_node:
        The name of the device or signal.

    :param signals:
        A dictionary mapping signal names to `SignalDetails` objects.

    :param sub_devices:
        A dictionary mapping sub-device names to their corresponding `PviTree` objects.

    :param vector_children:
        A list of `PviTree` objects representing child devices of a vector device.
    """

    pvi_pv: str
    root_node: str
    signals: dict[str, SignalDetails] = Field(default={})
    sub_devices: dict[str, PviTree] = Field(default={})
    vector_children: list[PviTree] = Field(default=[])

    @classmethod
    async def build_device_tree(cls, name: str, pvi_pv: str, timeout: float):
        """Recursively build a PviTree from a top level device.

        Starting from the top-level device, this classmethod performs
        post-order traversal over the served PVI structure, populating
        a PviTree from the bottom up.

        :param name: Device name
        :param pvi_pv: Device PVI PV
        :param timeout: Timeout on pvget
        """
        pvi_structure = await pvget_with_timeout(pvi_pv, timeout)
        entries: dict[str, Entry] = pvi_structure["value"].todict()

        vector_children: list[PviTree] = []

        sub_trees, signal_details = await asyncio.gather(
            gather_dict(
                {
                    entry_name: cls.build_device_tree(entry_name, entry["d"], 10)
                    for entry_name, entry in entries.items()
                    if set(entry) == {"d"}
                }
            ),
            gather_dict(
                {
                    entry_name: SignalDetails.from_entry(entry)
                    for entry_name, entry in entries.items()
                    if set(entry) != {"d"}
                }
            ),
        )

        # Filter vector children out of stand-alone devices
        for child_name in list(sub_trees):
            if m := re.match(r"^__(\d+)$", child_name):
                sub_tree = sub_trees.pop(child_name)
                sub_tree.root_node = m.group(1)
                vector_children.append(sub_tree)

        return PviTree(
            pvi_pv=pvi_pv,
            root_node=name,
            signals=signal_details,
            sub_devices=sub_trees,
            vector_children=vector_children,
        )

    def __str__(self) -> str:
        """Print a readable top layer of the PviTree."""
        sub_devices = {
            child_name: child_tree.pvi_pv
            for child_name, child_tree in self.sub_devices.items()
        }
        signals = {
            signal_name: {
                signal_details.signal_type: [
                    signal_details.read_pv,
                    signal_details.write_pv,
                ]
            }
            for signal_name, signal_details in self.signals.items()
        }
        return f"{self.root_node}: {self.pvi_pv}\n{sub_devices=}\n{signals=}"
