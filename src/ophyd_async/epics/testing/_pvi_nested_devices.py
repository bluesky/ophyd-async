from pathlib import Path
from typing import Annotated as A

from ophyd_async.core import (
    Device,
    DeviceMap,
    DeviceVector,
    SignalRW,
    TriggerableCommand,
)
from ophyd_async.epics.core import EpicsDevice, PvSuffix

PVI_NESTED_RECORDS = Path(__file__).parent / "_pvi_nested_records.db"


class EpicsTestPviLeafDevice(Device):
    """Leaf sub-device for `child` and `device_vector` on EpicsTestPviNestedDevice."""

    signal_rw: SignalRW[int]
    signal_x: TriggerableCommand


class EpicsTestPviNestedDevice(EpicsDevice):
    """Real-IOC-backed structural PVI test device.

    Exercises PviDeviceConnector's handling of nested sub-devices,
    DeviceVector of devices, DeviceVector of signals, DeviceVector of
    commands, and an Optional signal absent from the served tree -- the
    structural mechanics that tests/unit_tests/epics/pvi/test_pvi.py's
    Block1-Block5 classes exercise only against a *mocked* PVI tree.
    Construct with `with_pvi=True`.

    The served PVI tree also includes an `extra_devices` DeviceVector that
    is deliberately *not* annotated here, to prove that PviDeviceConnector
    fills in undeclared DeviceVectors of devices dynamically.

    Legacy list-based vector encoding (`PviTree._handle_legacy_entry`) is
    deliberately not covered here: it's exclusively produced by
    pandablocks-ioc's own hand-rolled PVA server, not something a
    QSRV2/db-file-based IOC can construct declaratively, so it stays
    covered by the existing mock-only unit test instead.
    """

    signal_rw: SignalRW[int]
    signal_x: TriggerableCommand
    child: EpicsTestPviLeafDevice
    device_vector: DeviceVector[EpicsTestPviLeafDevice]
    signal_vector: DeviceVector[SignalRW[float]]
    command_vector: DeviceVector[TriggerableCommand]
    optional_signal: SignalRW[int] | None


class EpicsTestPviMapDevice(EpicsDevice):
    """Real-IOC-backed `DeviceMap` test device, served under the `mapd:` group.

    Proves that a `DeviceMap` is created only from an explicit `DeviceMap[...]`
    annotation and filled from a node's *normal* named entries, keyed by name
    (`signal_map` -> `{"a", "b"}`, `device_map` -> `{"one", "two"}`), with each
    entry type-checked against the map's element type -- the counterpart to
    `EpicsTestPviNestedDevice`'s integer-keyed `DeviceVector`s. Construct with
    `with_pvi=True` and a prefix ending `mapd:`.
    """

    signal_map: DeviceMap[SignalRW[float]]
    device_map: DeviceMap[EpicsTestPviLeafDevice]


class EpicsTestPviAgreeingPvSuffixDevice(EpicsDevice):
    """Connects to the same served PVI tree as `EpicsTestPviNestedDevice`.

    Addresses its children with a `PvSuffix` *as well as* via PVI, naming the
    same PVs the served tree does. PVI is the one that fills them; the
    annotations are only cross-checked against it, so connecting succeeds.
    Construct with `with_pvi=True`.
    """

    signal_rw: A[SignalRW[int], PvSuffix("signal_rw")]
    child: A[EpicsTestPviLeafDevice, PvSuffix("child:")]


class EpicsTestPviDisagreeingDeviceDevice(EpicsDevice):
    """Connects to the same served PVI tree as `EpicsTestPviNestedDevice`.

    Gives `child` a `PvSuffix` naming a different PVI PV to the served one, so
    connecting must raise rather than silently take PVI's. The sub-device
    counterpart of `EpicsTestPviDisagreeingSuffixDevice`, which covers a
    disagreeing Signal. Construct with `with_pvi=True`.
    """

    child: A[EpicsTestPviLeafDevice, PvSuffix("not_child:")]


class EpicsTestPviMapOverVectorDevice(EpicsDevice):
    """Connects to the same served PVI tree as `EpicsTestPviNestedDevice`.

    Annotates `device_vector` -- which PVI serves as integer-keyed "__N" entries
    -- as a `DeviceMap`. A `DeviceMap` can only hold the named entries of a node,
    so its "__N" children have nowhere to go and connecting must raise rather
    than yield a map that has silently dropped them. Construct with
    `with_pvi=True`.
    """

    device_vector: DeviceMap[EpicsTestPviLeafDevice]


class EpicsTestPviNestedDeviceMissingChild(EpicsDevice):
    """Connects to the same served PVI tree as EpicsTestPviNestedDevice.

    Declares an extra required (non-Optional) sub-device the server
    doesn't actually provide -- demonstrates that connecting raises a clear
    RuntimeError when a required field can't be resolved via PVI (the
    mirror image of `optional_signal` above, which is allowed to be
    absent).
    """

    signal_rw: SignalRW[int]
    missing_child: EpicsTestPviLeafDevice
