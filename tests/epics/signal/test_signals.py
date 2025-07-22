import asyncio
import os
import time
import typing
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from typing import Generic, Literal, TypeVar, get_args

import bluesky.plan_stubs as bps
import numpy as np
import numpy.typing as npt
import pytest
import yaml
from aioca import purge_channel_caches
from bluesky.protocols import Location
from event_model import Dtype, Limits, LimitsRange
from ophyd.signal import EpicsSignal

from ophyd_async.core import (
    Array1D,
    NotConnected,
    Signal,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
    Table,
    YamlSettingsProvider,
    observe_value,
    soft_signal_r_and_setter,
)
from ophyd_async.epics.core import (
    CaSignalBackend,
    PvaSignalBackend,
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_signal_x,
)
from ophyd_async.epics.core._util import format_datatype  # noqa: PLC2701
from ophyd_async.epics.testing import (
    EpicsTestEnum,
    EpicsTestIocAndDevices,
    EpicsTestSubsetEnum,
    EpicsTestTable,
)
from ophyd_async.plan_stubs import (
    apply_settings,
    ensure_connected,
    retrieve_settings,
    store_settings,
)
from ophyd_async.testing import MonitorQueue, assert_describe_signal

T = TypeVar("T")
Protocol = Literal["ca", "pva"]


TIMEOUT = 30.0 if os.name == "nt" else 3.0


@pytest.fixture(scope="module")
def ioc_devices():
    ioc_devices = EpicsTestIocAndDevices()
    ioc_devices.ioc.start()
    yield ioc_devices
    # Purge the channel caches before we stop the IOC to stop
    # RuntimeError: Event loop is closed errors on teardown
    purge_channel_caches()
    ioc_devices.ioc.stop()
    # Print the IOC process output so in the case of a failing test
    # we will see if anything on the IOC side also failed
    print(ioc_devices.ioc.output)


class ExpectedData(Generic[T]):
    def __init__(
        self, initial: T, put: T, dtype: Dtype, dtype_numpy: str | list, **metadata
    ):
        self.initial = initial
        self.put = put
        self.metadata = dict(dtype=dtype, dtype_numpy=dtype_numpy, **metadata)


async def assert_monitor_then_put(
    signal: SignalR[SignalDatatypeT],
    initial_value: SignalDatatypeT,
    put_value: SignalDatatypeT,
    metadata: dict,
    signal_set: Callable[[SignalDatatypeT], Awaitable[None]] | None = None,
):
    if signal_set is None:
        assert isinstance(signal, SignalRW)
        signal_set = signal.set
    await signal.connect(timeout=1)
    with MonitorQueue(signal) as q:
        # Check initial value
        await q.assert_updates(initial_value)
        # Check descriptor
        if isinstance(initial_value, np.ndarray):
            shape = list(initial_value.shape)
        elif isinstance(initial_value, list | Table):
            shape = [len(initial_value)]
        else:
            shape = []
        await assert_describe_signal(signal, shape=shape, **metadata)
        # Put to new value and check it
        await signal_set(put_value)
        await q.assert_updates(put_value)


# Can be removed once numpy >=2 is pinned.
scalar_int_dtype = (
    "<i4" if os.name == "nt" and np.version.version.startswith("1.") else "<i8"
)
CA_PVA_INFERRED = {
    "a_int": ExpectedData(
        42,
        43,
        "integer",
        scalar_int_dtype,
        limits=Limits(
            control=LimitsRange(low=10, high=90),
            warning=LimitsRange(low=5, high=96),
            alarm=LimitsRange(low=2, high=98),
            display=LimitsRange(low=0, high=100),
        ),
        units="",
    ),
    "partialint": ExpectedData(
        42,
        43,
        "integer",
        scalar_int_dtype,
        limits=Limits(
            control=LimitsRange(low=10.0, high=90.0),
            alarm=LimitsRange(low=2.0, high=98.0),
            display=LimitsRange(low=0.0, high=100.0),
        ),
        units="",
    ),
    "lessint": ExpectedData(
        42,
        43,
        "integer",
        scalar_int_dtype,
        limits=Limits(
            # control = display if DRVL, DRVH not set
            control=LimitsRange(low=0.0, high=100.0),
            # LOPR, HOPR
            display=LimitsRange(low=0.0, high=100.0),
            # LOW, HIGH
            warning=LimitsRange(low=2.0, high=98.0),
        ),
        units="",
    ),
    "a_float": ExpectedData(3.141, 43.5, "number", "<f8", precision=1, units="mm"),
    "a_str": ExpectedData("hello", "goodbye", "string", "|S40"),
    "uint8a": ExpectedData(
        np.array([0, 255], dtype=np.uint8),
        np.array([218], dtype=np.uint8),
        "array",
        "|u1",
        units="",
    ),
    "int16a": ExpectedData(
        np.array([-32768, 32767], dtype=np.int16),
        np.array([-855], dtype=np.int16),
        "array",
        "<i2",
        units="",
    ),
    "int32a": ExpectedData(
        np.array([-2147483648, 2147483647], dtype=np.int32),
        np.array([-2], dtype=np.int32),
        "array",
        "<i4",
        units="",
    ),
    "float32a": ExpectedData(
        np.array([0.000002, -123.123], dtype=np.float32),
        np.array([1.0], dtype=np.float32),
        "array",
        "<f4",
        units="",
        precision=0,
    ),
    "float64a": ExpectedData(
        np.array([0.1, -12345678.123], dtype=np.float64),
        np.array([0.2], dtype=np.float64),
        "array",
        "<f8",
        units="",
        precision=0,
    ),
    "stra": ExpectedData(["five", "six", "seven"], ["nine", "ten"], "array", "|S40"),
}
PVA_INFERRED = {
    "int8a": ExpectedData(
        np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
        np.array([-8, 3, 44], dtype=np.int8),
        "array",
        "|i1",
        units="",
    ),
    "uint16a": ExpectedData(
        np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
        np.array([5666], dtype=np.uint16),
        "array",
        "<u2",
        units="",
    ),
    "uint32a": ExpectedData(
        np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
        np.array([1022233], dtype=np.uint32),
        "array",
        "<u4",
        units="",
    ),
    "int64a": ExpectedData(
        np.array([-(2**63 - 1), 2**63 - 1, 0, 1, 2, 3, 4], dtype=np.int64),
        np.array([-3], dtype=np.int64),
        "array",
        "<i8",
        units="",
    ),
    "uint64a": ExpectedData(
        np.array([0, 2**63 - 1, 0, 1, 2, 3, 4], dtype=np.uint64),
        np.array([995444], dtype=np.uint64),
        "array",
        "<u8",
        units="",
    ),
}


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize(
    "protocol,name,data",
    [("ca", k, v) for k, v in CA_PVA_INFERRED.items()]  # ca/pva shared for ca
    + [("pva", k, v) for k, v in CA_PVA_INFERRED.items()]  # ca/pva shared for pva
    + [("pva", k, v) for k, v in PVA_INFERRED.items()],  # pva only
)
async def test_epics_get_put_monitor_for_inferred_types(
    ioc_devices: EpicsTestIocAndDevices,
    protocol: Protocol,
    name: str,
    data: ExpectedData,
):
    # With the given datatype, check we have the correct initial value and putting
    # works
    device_signal = ioc_devices.get_signal(protocol, name)
    await assert_monitor_then_put(device_signal, data.initial, data.put, data.metadata)
    # With datatype guessed from CA/PVA, check we can set it back to the initial value
    guess_signal = epics_signal_rw(None, device_signal.source)  # type: ignore
    await assert_monitor_then_put(guess_signal, data.put, data.initial, data.metadata)


CA_PVA_OVERRIDE = {
    "longstr": ExpectedData(
        "a string that is just longer than forty characters",
        "another string that is just longer than forty characters",
        "string",
        "|S40",
    ),
    "longstr2": ExpectedData(
        "a string that is just longer than forty characters",
        "another string that is just longer than forty characters",
        "string",
        "|S40",
    ),
    "a_bool": ExpectedData(True, False, "boolean", dtype_numpy="|b1"),
    "bool_unnamed": ExpectedData(True, False, "boolean", dtype_numpy="|b1"),
    "enum": ExpectedData(
        EpicsTestEnum.B,
        EpicsTestEnum.C,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    "subset_enum": ExpectedData(
        EpicsTestSubsetEnum.B,
        EpicsTestSubsetEnum.A,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    "float_prec_0": ExpectedData(3, 4, "integer", scalar_int_dtype, units="mm"),
}
PVA_OVERRIDE = {}


@pytest.mark.timeout(TIMEOUT + 0.6)
@pytest.mark.parametrize(
    "protocol,name,data",
    [("ca", k, v) for k, v in CA_PVA_OVERRIDE.items()]  # ca/pva shared for ca
    + [("pva", k, v) for k, v in CA_PVA_OVERRIDE.items()]  # ca/pva shared for pva
    + [("pva", k, v) for k, v in PVA_OVERRIDE.items()],  # pva only
)
async def test_epics_get_put_monitor_for_override_types(
    ioc_devices: EpicsTestIocAndDevices,
    protocol: Protocol,
    name: str,
    data: ExpectedData,
):
    # With the given datatype, check we have the correct initial value and putting
    # works
    device_signal = ioc_devices.get_signal(protocol, name)
    await assert_monitor_then_put(device_signal, data.initial, data.put, data.metadata)
    # Then using the same signal, check that putting back works
    await assert_monitor_then_put(device_signal, data.put, data.initial, data.metadata)


def _example_table_dtype_numpy(guess: bool) -> list:
    return [
        # natively bool fields are uint8, so if we don't provide a Table
        # subclass to specify bool, that is what we get
        ("bool", "|u1" if guess else "|b1"),
        ("int", "<i4"),
        ("float", "<f8"),
        ("str", "|S40"),
        ("enum", "|S40"),
    ]


@pytest.mark.timeout(TIMEOUT)
async def test_pva_table(ioc_devices: EpicsTestIocAndDevices):
    initial = EpicsTestTable(
        a_bool=np.array([False, False, True, True], np.bool_),
        a_int=np.array([1, 8, -9, 32], np.int32),
        a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        a_str=["Hello", "World", "Foo", "Bar"],
        a_enum=[EpicsTestEnum.A, EpicsTestEnum.B, EpicsTestEnum.A, EpicsTestEnum.C],
    )
    put = EpicsTestTable(
        a_bool=np.array([True, False], np.bool_),
        a_int=np.array([-5, 32], np.int32),
        a_float=np.array([8.5, -6.97], np.float64),
        a_str=["Hello", "Bat"],
        a_enum=[EpicsTestEnum.C, EpicsTestEnum.B],
    )
    dtype_numpy = [
        ("a_bool", "|b1"),
        ("a_int", "<i4"),
        ("a_float", "<f8"),
        ("a_str", "|S40"),
        ("a_enum", "|S40"),
    ]
    signal = ioc_devices.pva_device.table
    await assert_monitor_then_put(
        signal,
        initial,
        put,
        {"dtype": "array", "dtype_numpy": dtype_numpy},
    )
    initial_plain_table = Table(
        a_bool=np.array([0, 0, 1, 1], np.uint8),
        a_int=np.array([1, 8, -9, 32], np.int32),
        a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        a_str=["Hello", "World", "Foo", "Bar"],
        a_enum=["Aaa", "Bbb", "Aaa", "Ccc"],
    )
    put_plain_table = Table(
        a_bool=np.array([1, 0], np.uint8),
        a_int=np.array([-5, 32], np.int32),
        a_float=np.array([8.5, -6.97], np.float64),
        a_str=["Hello", "Bat"],
        a_enum=["Ccc", "Bbb"],
    )
    dtype_numpy_plain_table = [
        # Plain tables will use the underlying epics datatype, in this
        # case uint8
        ("a_bool", "|u1"),
        ("a_int", "<i4"),
        ("a_float", "<f8"),
        ("a_str", "|S40"),
        ("a_enum", "|S40"),
    ]
    await assert_monitor_then_put(
        epics_signal_rw(None, signal.source),  # type: ignore
        put_plain_table,
        initial_plain_table,
        {"dtype": "array", "dtype_numpy": dtype_numpy_plain_table},
    )


@pytest.mark.timeout(TIMEOUT)
async def test_pva_ntndarray(ioc_devices: EpicsTestIocAndDevices):
    data = ExpectedData(np.zeros((2, 3)), np.arange(6).reshape((2, 3)), "array", "<i8")
    signal = ioc_devices.pva_device.ntndarray

    # Backdoor into the "raw" data underlying the NDArray in QSrv
    # not supporting direct writes to NDArray at the moment.
    raw_signal = epics_signal_rw(Array1D[np.int64], signal.source + ":data")
    await raw_signal.connect()

    async def signal_set(v):
        await raw_signal.set(v.flatten())

    await assert_monitor_then_put(
        signal, data.initial, data.put, data.metadata, signal_set
    )
    await assert_monitor_then_put(
        signal, data.put, data.initial, data.metadata, signal_set
    )


@pytest.mark.timeout(TIMEOUT)
async def test_writing_to_ndarray_raises_typeerror(ioc_devices: EpicsTestIocAndDevices):
    signal = epics_signal_rw(np.ndarray, ioc_devices.pva_device.ntndarray.source)
    await signal.connect()
    with pytest.raises(TypeError):
        await signal.set(np.zeros((6,), dtype=np.int64))


@pytest.mark.timeout(TIMEOUT)
async def test_invalid_enum_choice_raises_valueerror(
    ioc_devices: EpicsTestIocAndDevices,
):
    signal = ioc_devices.ca_device.enum_str_fallback
    await signal.connect()
    with pytest.raises(ValueError) as exc:
        await signal.set("Ddd")
    assert "Ddd is not a valid choice for" in str(exc.value)
    assert "ca:enum_str_fallback, valid choices: ['Aaa', 'Bbb', 'Ccc']" in str(
        exc.value
    )


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_typing_sequence_str_signal_connects(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    # Explicitly test that we can connect to a typing.Sequence[str] signal
    # rather than a collections.abc.Sequence[str] which is more normal
    signal = epics_signal_rw(typing.Sequence[str], ioc_devices.get_pv(protocol, "stra"))
    await signal.connect()


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_error_raised_on_disconnected_PV(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    signal = epics_signal_rw(bool, ioc_devices.get_pv(protocol, "bool"))
    await signal.connect()
    # The below will work without error
    await signal.set(False)
    # Override the PV so it fails
    signal._connector.backend.write_pv = "DisconnectedPv"  # type: ignore
    with pytest.raises(asyncio.TimeoutError, match=f"{protocol}://DisconnectedPv"):
        await signal.set(True, timeout=0.1)


class BadEnum(StrictEnum):
    A = "Aaa"
    B = "B"
    C = "Ccc"


class EnumNoString(Enum):
    A = "Aaa"


class SubsetEnumWrongChoices(SubsetEnum):
    A = "Aaa"
    B = "B"
    C = "Ccc"


def test_enum_equality():
    """Check that we are allowed to replace the passed datatype enum from a signal with
    a version generated from the signal with at least all of the same values, but
    possibly more.
    """

    class GeneratedChoices(StrictEnum):
        A = "Aaa"
        B = "B"
        C = "Ccc"

    class ExtendedGeneratedChoices(StrictEnum):
        A = "Aaa"
        B = "B"
        C = "Ccc"
        D = "Ddd"

    for enum_class in (GeneratedChoices, ExtendedGeneratedChoices):
        assert BadEnum.A == enum_class.A
        assert BadEnum.A.value == enum_class.A
        assert BadEnum.A.value == enum_class.A.value
        assert BadEnum(enum_class.A) is BadEnum.A
        assert BadEnum(enum_class.A.value) is BadEnum.A
        assert not BadEnum == enum_class

    # We will always PUT BadEnum by String, and GET GeneratedChoices by index,
    # so shouldn't ever run across this from conversion code, but may occur if
    # casting returned values or passing as enum rather than value.
    with pytest.raises(ValueError):
        BadEnum(ExtendedGeneratedChoices.D)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
@pytest.mark.parametrize(
    "typ, suff, errors",
    [
        (
            BadEnum,
            "enum",
            (
                "has choices ('Aaa', 'Bbb', 'Ccc')",
                "but <enum 'BadEnum'>",
                "requested ['Aaa', 'B', 'Ccc'] to be strictly equal",
            ),
        ),
        (
            SubsetEnumWrongChoices,
            "enum",
            (
                "has choices ('Aaa', 'Bbb', 'Ccc')",
                "but <enum 'SubsetEnumWrongChoices'>",
                "requested ['Aaa', 'B', 'Ccc'] to be a subset",
            ),
        ),
        (
            int,
            "str",
            ("with inferred datatype str", "cannot be coerced to int"),
        ),
        (
            str,
            "float",
            ("with inferred datatype float", "cannot be coerced to str"),
        ),
        (
            str,
            "stra",
            ("with inferred datatype Sequence[str]", "cannot be coerced to str"),
        ),
        (
            int,
            "uint8a",
            ("with inferred datatype Array1D[np.uint8]", "cannot be coerced to int"),
        ),
        (
            float,
            "enum",
            ("with inferred datatype str", "cannot be coerced to float"),
        ),
        (
            Array1D[np.int32],
            "float64a",
            (
                "with inferred datatype Array1D[np.float64]",
                "cannot be coerced to Array1D[np.int32]",
            ),
        ),
        (
            EnumNoString,
            "enum2",
            (
                "<enum 'EnumNoString'> should inherit from ",
                "ophyd_async.core.SubsetEnum or ophyd_async.core.StrictEnum",
            ),
        ),
    ],
)
async def test_backend_wrong_type_errors(
    ioc_devices: EpicsTestIocAndDevices, typ, suff, errors, protocol: Protocol
):
    signal = epics_signal_rw(typ, ioc_devices.get_pv(protocol, suff))
    with pytest.raises(TypeError) as cm:
        await signal.connect()
    for error in errors:
        assert error in str(cm.value)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_backend_put_enum_string(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    signal = ioc_devices.get_signal(protocol, "enum2")
    await signal.connect()
    await signal.set("Ccc")
    assert (
        Location(setpoint=EpicsTestEnum.C, readback=EpicsTestEnum.C)
        == await signal.locate()
    )
    val = await signal.get_value()
    assert val == "Ccc"
    assert val is EpicsTestEnum.C
    assert repr(val) == "<EpicsTestEnum.C: 'Ccc'>"


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_non_existent_errors(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    signal = epics_signal_rw(str, "non-existent")
    with pytest.raises(NotConnected):
        await signal.connect(timeout=0.1)


@pytest.mark.parametrize(
    "dt,expected",
    [
        (Array1D[np.int32], "Array1D[np.int32]"),
        (np.ndarray, "ndarray"),
        (npt.NDArray[np.float64], "Array1D[np.float64]"),
    ],
)
def test_format_error_message(dt, expected):
    assert format_datatype(dt) == expected


def test_make_backend_fails_for_different_transports():
    read_pv = "test"
    write_pv = "pva://test"

    with pytest.raises(
        TypeError,
        match=f"Differing protocols: {read_pv} has EpicsProtocol.CA,"
        + f" {write_pv} has EpicsProtocol.PVA",
    ):
        epics_signal_rw(str, read_pv, write_pv)


def _get_epics_backend(signal: Signal) -> CaSignalBackend | PvaSignalBackend:
    backend = signal._connector.backend
    assert isinstance(backend, CaSignalBackend | PvaSignalBackend)
    return backend


def test_signal_helpers():
    read_write = epics_signal_rw(int, "ReadWrite")
    assert _get_epics_backend(read_write).read_pv == "ReadWrite"
    assert _get_epics_backend(read_write).write_pv == "ReadWrite"

    read_write_rbv_manual = epics_signal_rw(int, "ReadWrite_RBV", "ReadWrite")
    assert _get_epics_backend(read_write_rbv_manual).read_pv == "ReadWrite_RBV"
    assert _get_epics_backend(read_write_rbv_manual).write_pv == "ReadWrite"

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite")
    assert _get_epics_backend(read_write_rbv).read_pv == "ReadWrite_RBV"
    assert _get_epics_backend(read_write_rbv).write_pv == "ReadWrite"

    read_write_rbv_suffix = epics_signal_rw_rbv(int, "ReadWrite", read_suffix=":RBV")
    assert _get_epics_backend(read_write_rbv_suffix).read_pv == "ReadWrite:RBV"
    assert _get_epics_backend(read_write_rbv_suffix).write_pv == "ReadWrite"

    read_write_rbv_w_field = epics_signal_rw_rbv(int, "ReadWrite.VAL")
    assert _get_epics_backend(read_write_rbv_w_field).read_pv == "ReadWrite_RBV.VAL"
    assert _get_epics_backend(read_write_rbv_w_field).write_pv == "ReadWrite.VAL"

    read = epics_signal_r(int, "Read")
    assert _get_epics_backend(read).read_pv == "Read"

    write = epics_signal_w(int, "Write")
    assert _get_epics_backend(write).write_pv == "Write"

    execute = epics_signal_x("Execute")
    assert _get_epics_backend(execute).write_pv == "Execute"


def test_signal_helpers_explicit_read_timeout():
    # Check that we can adjust the _timeout attribute, which is used
    # for example during await signal.get_value()

    read_write = epics_signal_rw(int, "ReadWrite", timeout=123)
    assert read_write._timeout == 123

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite", timeout=456)
    assert read_write_rbv._timeout == 456

    read = epics_signal_r(int, "Read", timeout=789)
    assert read._timeout == 789

    write = epics_signal_w(int, "Write", timeout=987)
    assert write._timeout == 987

    execute = epics_signal_x("Execute", timeout=654)
    assert execute._timeout == 654


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_signals_created_for_not_prec_0_float_cannot_use_int(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv(protocol, "float_prec_1"))
    with pytest.raises(
        TypeError,
        match="float_prec_1 with inferred datatype float.* cannot be coerced to int",
    ):
        await sig.connect()


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_bool_works_for_mismatching_enums(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    pv_name = ioc_devices.get_pv(protocol, "bool")
    sig = epics_signal_rw(bool, pv_name, pv_name + "_unnamed")
    await sig.connect()


@pytest.mark.timeout(TIMEOUT)
async def test_can_read_using_ophyd_async_then_ophyd(
    RE, ioc_devices: EpicsTestIocAndDevices
):
    ophyd_async_sig = epics_signal_rw(float, ioc_devices.get_pv("ca", "float_prec_1"))
    await ophyd_async_sig.connect()
    ophyd_signal = EpicsSignal(ioc_devices.get_pv("ca", "float_prec_0").split("://")[1])
    ophyd_signal.wait_for_connection(timeout=5)

    def a_plan():
        yield from bps.rd(ophyd_async_sig)
        yield from bps.rd(ophyd_signal)

    RE(a_plan())


def test_signal_module_emits_deprecation_warning():
    with pytest.deprecated_call():
        import ophyd_async.epics.signal  # noqa: F401


@pytest.mark.timeout(TIMEOUT + 0.6)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_observe_ticking_signal_with_busy_loop(
    ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv("ca", "ticking"))
    await sig.connect()

    recv = []

    async def watch():
        async for val in observe_value(sig, done_timeout=0.4):
            time.sleep(0.3)
            recv.append(val)

    start = time.monotonic()

    with pytest.raises(asyncio.TimeoutError):
        await watch()
    assert time.monotonic() - start == pytest.approx(0.6, abs=0.1)
    assert len(recv) == 2
    # Don't check values as CA and PVA have different algorithms for
    # dropping updates for slow callbacks


HERE = Path(__file__).absolute().parent


@pytest.mark.timeout(TIMEOUT + 0.5)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_retrieve_apply_store_settings(
    RE, ioc_devices: EpicsTestIocAndDevices, protocol: Protocol, tmp_path
):
    tmp_provider = YamlSettingsProvider(tmp_path)
    expected_provider = YamlSettingsProvider(HERE)
    device = ioc_devices.get_device(protocol)

    def a_plan():
        yield from ensure_connected(device)
        settings = yield from retrieve_settings(
            expected_provider, f"test_yaml_save_{protocol}", device
        )
        yield from apply_settings(settings)
        yield from store_settings(tmp_provider, "test_file", device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(HERE / f"test_yaml_save_{protocol}.yaml") as expected_file:
                # If this test fails because you added a signal, then you can regenerate
                # the test data with:
                # cp /tmp/pytest-of-root/pytest-current/test_retrieve_apply_store_sett0/test_file.yaml tests/epics/signal/test_yaml_save_ca.yaml  # noqa: E501
                # cp /tmp/pytest-of-root/pytest-current/test_retrieve_apply_store_sett1/test_file.yaml tests/epics/signal/test_yaml_save_pva.yaml  # noqa: E501
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(a_plan())


@pytest.mark.timeout(TIMEOUT + 0.5)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_put_completion(
    RE, ioc_devices: EpicsTestIocAndDevices, protocol: Protocol
):
    # Check that we can put to an epics signal and wait for put completion
    slow_seq_pv = ioc_devices.get_pv(protocol, "slowseq")
    slow_seq = epics_signal_rw(int, slow_seq_pv)
    await slow_seq.connect()

    # First, do a set with blocking and make sure it takes a while
    start = time.monotonic()
    await slow_seq.set(1, wait=True)
    stop = time.monotonic()
    assert stop - start == pytest.approx(0.5, rel=0.1)

    # Then, make sure if we don't wait it returns ~instantly
    start = time.monotonic()
    await slow_seq.set(2, wait=False)
    stop = time.monotonic()
    assert stop - start < 0.1

    # Time for completion callback to have finished before moving to
    # next test / iteration - without this, running this test multiple
    # times in a row will fail even-numbered runs.
    await asyncio.sleep(0.5)


@pytest.mark.timeout(TIMEOUT + 0.5)
async def test_setting_with_none_uses_initial_value_of_pv(
    ioc_devices: EpicsTestIocAndDevices,
):
    sig_rw = epics_signal_rw(int, ioc_devices.get_pv("pva", "slowseq"))
    await sig_rw.connect()
    initial_data = await sig_rw.read()
    initial_value, initial_timestamp = (
        initial_data[""]["value"],
        initial_data[""]["timestamp"],
    )

    # This mimics triggering a SignalX
    await sig_rw.set(None)  # type: ignore

    current_data = await sig_rw.read()
    assert (
        initial_value == current_data[""]["value"]
        and initial_timestamp != current_data[""]["timestamp"]
    )


@pytest.mark.timeout(TIMEOUT + 0.5)
async def test_signal_retries_when_timeout(
    ioc_devices: EpicsTestIocAndDevices,
):
    # put callback on slowseq in 0.5s, so if waited, this will fail to set
    sig_rw_times_out = epics_signal_rw(
        int, ioc_devices.get_pv("pva", "slowseq"), attempts=3, timeout=0.1
    )
    await sig_rw_times_out.connect()

    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await sig_rw_times_out.set(1, wait=True)
    stop = time.monotonic()
    # signal tries to set 3 times, so 3 * timeout
    assert stop - start == pytest.approx(0.3, abs=0.1)


async def test_signal_timestamp_is_same_format_as_soft_signal_timestamp(
    RE, ioc_devices: EpicsTestIocAndDevices
):
    sim_sig, sim_sig_setter = soft_signal_r_and_setter(float)
    real_sig = epics_signal_rw(float, ioc_devices.get_pv("ca", "float_prec_1"))
    await real_sig.connect(timeout=30)

    await real_sig.set(10)
    sim_sig_setter(20)

    real_data = await real_sig.read()
    sim_data = await sim_sig.read()

    assert abs(real_data[""]["timestamp"] - sim_data[""]["timestamp"]) < 0.1
