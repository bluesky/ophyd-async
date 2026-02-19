from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import (
    Field,
    computed_field,
    field_validator,
)

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
                pvi_pv=self.pvi_pv, timeout=timeout
            )
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
                for (
                    vector_index,
                    vector_child,
                ) in device_sub_tree.vector_children.items():
                    if device_sub_tree.is_signal_vector:
                        # DeviceVector of signals
                        if isinstance(vector_child, SignalDetails):
                            backend = self.filler.fill_child_signal(
                                device_name, vector_child.signal_type, vector_index
                            )
                            backend.read_pv = vector_child.read_pv
                            backend.write_pv = vector_child.write_pv
                        else:
                            raise TypeError(
                                "Failed to fill DeviceVector. "
                                f"Expected SignalDetails, got {type(vector_child)}"
                            )
                    else:
                        # DeviceVector of devices
                        if isinstance(vector_child, PviTree):
                            connector = self.filler.fill_child_device(
                                device_name, vector_index=vector_index
                            )
                            connector.pvi_tree = vector_child
                            connector.pvi_pv = vector_child.pvi_pv
                        else:
                            raise TypeError(
                                "Failed to fill DeviceVector. "
                                f"Expected PviTree, got {type(vector_child)}"
                            )
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
    def from_entry(cls, entry: dict[str, str]) -> SignalDetails:
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
        signals={},
        sub_devices={},
        vector_children=[
            PviTree(pvi_pv="TEST-PANDA:Calc:2:PVI", signals={}, ...),
            PviTree(pvi_pv="TEST-PANDA:Calc:1:PVI", signals={}, ...)
        ]
    )
    ```

    This is similar for vectors of signals, where `vector_children` would instead
    be populated with `SignalDetails`

    Example 3: A device with legacy vector children
    -----------------------------------------
    Legacy PVI vector structure is supported, for backwards compatability
    with pandablocks-ioc, where vector children are represented as:

    ```
    {
        "calc": [None, {"d": "TEST-PANDA:Calc1:PVI"}, {"d": "TEST-PANDA:Calc2:PVI"}],
    }
    ```
    generate the same PviTree as in Example 2, excluding a PVI PV.

    :param pvi_pv:
        The PVI PV of the device.

    :param signals:
        A mapping of signal names to `SignalDetails` objects.

    :param sub_devices:
        A mapping of sub-device names to their corresponding `PviTree` objects.

    :param vector_children:
        A mapping of int to `PviTree` objects representing child devices of a vector
        device.

    :attr is_signal_vector:
        A computed property returning True if any child device in `vector_children`
        is an instance of `SignalDetails`, else False.
    """

    pvi_pv: str = Field(default="")
    signals: Mapping[str, SignalDetails] = Field(default_factory=dict)
    sub_devices: Mapping[str, PviTree] = Field(default_factory=dict)
    vector_children: Mapping[int, PviTree | SignalDetails] = Field(default_factory=dict)

    @classmethod
    async def build_device_tree(cls, pvi_pv: str, timeout: float) -> PviTree:
        """Recursively build a PviTree from a top level device.

        Starting from the top-level device, this classmethod performs
        post-order traversal over the served PVI structure, populating
        a PviTree from the bottom up.

        :param name: Device name
        :param pvi_pv: Device PVI PV
        :param timeout: Timeout on pvget
        """
        pvi_structure = await pvget_with_timeout(pvi_pv, timeout)

        # An example entry is: {"d": "Prefix:Device:PVI", "rw": "Prefix:A"}
        # these entries are stored under the parent PVI structure name
        # for example, {"device": {"d": "Prefix:Device:PVI", "rw": "Prefix:A"}}
        entries: dict[str, dict[str, str]] = pvi_structure["value"].todict()

        signal_details = {
            entry_name: SignalDetails.from_entry(entries.pop(entry_name))
            for entry_name in list(entries)
            if not isinstance(entries[entry_name], list)
            and set(entries[entry_name]) != {"d"}
        }

        sub_trees = await gather_dict(
            {
                entry_name: cls._handle_legacy_entry(entry, timeout)
                if isinstance(entry, list)  # Found a legacy entry, try to handle
                else cls.build_device_tree(entry["d"], timeout)
                for entry_name, entry in entries.items()
            }
        )

        vector_children: dict[int, PviTree | SignalDetails] = {}
        # Filter vector children out of stand-alone devices

        for processed_entries in (sub_trees, signal_details):
            for child_name in list(processed_entries):
                if m := re.match(r"^__(\d+)$", child_name):
                    sub_tree = processed_entries.pop(child_name)
                    vector_children[int(m.group(1))] = sub_tree

        return PviTree(
            pvi_pv=pvi_pv,
            signals=signal_details,
            sub_devices=sub_trees,
            vector_children=vector_children,
        )

    @classmethod
    async def _handle_legacy_entry(
        cls, legacy_entry: list[None | dict[str, str]], timeout: float
    ) -> PviTree:
        sub_trees = await gather_dict(
            {
                vector_index: cls.build_device_tree(vector_entry["d"], timeout)
                for vector_index, vector_entry in enumerate(legacy_entry)
                if vector_entry is not None
            }
        )

        # Legacy FastCS vector should not contain child signals,
        # devices, or its own PVI PV.
        return PviTree(
            vector_children=sub_trees,
        )

    @computed_field
    @property
    def is_signal_vector(self) -> bool:
        return any(isinstance(v, SignalDetails) for v in self.vector_children.values())

    def __str__(self) -> str:
        """Print a readable top layer of the PviTree."""
        children = {
            child_name: tree.pvi_pv
            for child_name, tree in {**self.sub_devices, **self.vector_children}.items()
        }
        signals = {
            signal_name: (detail.signal_type.__name__, detail.read_pv, detail.write_pv)
            for signal_name, detail in self.signals.items()
        }
        return f"sub_devices={children}\nsignals={signals}"

    @field_validator("vector_children")
    @classmethod
    def _check_consistency_of_vector_children_type(
        cls,
        vector_children: Mapping[int, PviTree | SignalDetails],
    ):
        if not (
            all(
                isinstance(vector_child, SignalDetails)
                for vector_child in vector_children.values()
            )
            or all(
                isinstance(vector_child, PviTree)
                for vector_child in vector_children.values()
            )
        ):
            raise ValueError(
                "Failed to validate PviTree. "
                "vector_children must all be of type `SignalDetails` or `PviTree`. "
                f"Received mixed type: {vector_children=}"
            )
        return vector_children
