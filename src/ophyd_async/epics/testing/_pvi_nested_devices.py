from pathlib import Path

from ophyd_async.core import Device, DeviceVector, SignalRW, TriggerableCommand
from ophyd_async.epics.core import EpicsDevice

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
