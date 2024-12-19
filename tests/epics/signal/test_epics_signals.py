import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Generic, Literal, get_args

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from aioca import purge_channel_caches
from bluesky.protocols import Location
from event_model import Dtype, Limits, LimitsRange
from ophyd.signal import EpicsSignal

from ophyd_async.core import (
    Array1D,
    NotConnected,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
    T,
    Table,
    observe_value,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_signal_x,
)
from ophyd_async.epics.testing import (
    ExampleEnum,
    ExampleIocAndDevices,
    ExampleSubsetEnum,
    ExampleTable,
)
from ophyd_async.testing import MonitorQueue, assert_describe_signal

Protocol = Literal["ca", "pva"]


@pytest.fixture(scope="module")
def ioc_devices():
    ioc_devices = ExampleIocAndDevices()
    ioc_devices.ioc.start_ioc()
    yield ioc_devices
    # Purge the channel caches before we stop the IOC to stop
    # RuntimeError: Event loop is closed errors on teardown
    purge_channel_caches()
    ioc_devices.ioc.stop_ioc()


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
        await q.assert_updates(pytest.approx(initial_value))
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
        await q.assert_updates(pytest.approx(put_value))


CA_PVA_INFERRED = {
    "my_int": ExpectedData(
        42,
        43,
        "integer",
        "<i8",
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
        "<i8",
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
        "<i8",
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
    "my_float": ExpectedData(3.141, 43.5, "number", "<f8", precision=1, units="mm"),
    "my_str": ExpectedData("hello", "goodbye", "string", "|S40"),
    "enum": ExpectedData(
        ExampleEnum.B, ExampleEnum.C, "string", "|S40", choices=["Aaa", "Bbb", "Ccc"]
    ),
    "subset_enum": ExpectedData(
        ExampleSubsetEnum.B,
        ExampleSubsetEnum.A,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    "uint8a": ExpectedData([0, 255], [218], "array", "|u1", units=""),
    "int16a": ExpectedData([-32768, 32767], [-855], "array", "<i2", units=""),
    "int32a": ExpectedData([-2147483648, 2147483647], [-2], "array", "<i4", units=""),
    "float32a": ExpectedData(
        [0.000002, -123.123], [1.0], "array", "<f4", units="", precision=0
    ),
    "float64a": ExpectedData(
        [0.1, -12345678.123], [0.2], "array", "<f8", units="", precision=0
    ),
    "stra": ExpectedData(["five", "six", "seven"], ["nine", "ten"], "array", "|S40"),
}
PVA_INFERRED = {
    "int8a": ExpectedData([-128, 127], [-8, 3, 44], "array", "|i1", units=""),
    "uint16a": ExpectedData([0, 65535], [5666], "array", "<u2", units=""),
    "uint32a": ExpectedData([0, 4294967295], [1022233], "array", "<u4", units=""),
    "int64a": ExpectedData([-2147483649, 2147483648], [-3], "array", "<i8", units=""),
    "uint64a": ExpectedData([0, 4294967297], [995444], "array", "<u8", units=""),
}


@pytest.mark.parametrize(
    "protocol,name,data",
    [("ca", k, v) for k, v in CA_PVA_INFERRED.items()]  # ca/pva shared for ca
    + [("pva", k, v) for k, v in CA_PVA_INFERRED.items()]  # ca/pva shared for pva
    + [("pva", k, v) for k, v in PVA_INFERRED.items()],  # pva only
)
async def test_epics_get_put_monitor_for_inferred_types(
    ioc_devices: ExampleIocAndDevices,
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
    "my_bool": ExpectedData(True, False, "boolean", dtype_numpy="|b1"),
    "bool_unnamed": ExpectedData(True, False, "boolean", dtype_numpy="|b1"),
}
PVA_OVERRIDE = {}


@pytest.mark.parametrize(
    "protocol,name,data",
    [("ca", k, v) for k, v in CA_PVA_OVERRIDE.items()]  # ca/pva shared for ca
    + [("pva", k, v) for k, v in CA_PVA_OVERRIDE.items()]  # ca/pva shared for pva
    + [("pva", k, v) for k, v in PVA_OVERRIDE.items()],  # pva only
)
async def test_epics_get_put_monitor_for_override_types(
    ioc_devices: ExampleIocAndDevices,
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


async def test_pva_table(ioc_devices: ExampleIocAndDevices):
    initial = ExampleTable(
        bool=np.array([False, False, True, True], np.bool_),
        int=np.array([1, 8, -9, 32], np.int32),
        float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        str=["Hello", "World", "Foo", "Bar"],
        enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
    )
    put = ExampleTable(
        bool=np.array([True, False], np.bool_),
        int=np.array([-5, 32], np.int32),
        float=np.array([8.5, -6.97], np.float64),
        str=["Hello", "Bat"],
        enum=[ExampleEnum.C, ExampleEnum.B],
    )
    signal = ioc_devices.pva_device.table
    await assert_monitor_then_put(
        signal,
        initial,
        put,
        {"dtype": "array", "dtype_numpy": _example_table_dtype_numpy(True)},
    )
    await assert_monitor_then_put(
        epics_signal_rw(None, signal.source),  # type: ignore
        put,
        initial,
        {"dtype": "array", "dtype_numpy": _example_table_dtype_numpy(False)},
    )


async def test_pva_ntndarray(ioc_devices: ExampleIocAndDevices):
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


async def test_writing_to_ndarray_raises_typeerror(ioc_devices: ExampleIocAndDevices):
    signal = epics_signal_rw(np.ndarray, ioc_devices.pva_device.ntndarray.source)
    await signal.connect()
    with pytest.raises(TypeError):
        await signal.set(np.zeros((6,), dtype=np.int64))


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_error_raised_on_disconnected_PV(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
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
    ioc_devices: ExampleIocAndDevices, typ, suff, errors, protocol: Protocol
):
    signal = epics_signal_rw(typ, ioc_devices.get_pv(protocol, suff))
    with pytest.raises(TypeError) as cm:
        await signal.connect()
    for error in errors:
        assert error in str(cm.value)


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_backend_put_enum_string(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    signal = ioc_devices.get_signal(protocol, "enum2")
    await signal.connect()
    await signal.set("Ccc")
    assert (
        Location(setpoint=ExampleEnum.C, readback=ExampleEnum.C)
        == await signal.locate()
    )
    val = await signal.get_value()
    assert val == "Ccc"
    assert val is ExampleEnum.C
    assert repr(val) == "<ExampleEnum.C: 'Ccc'>"


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_non_existent_errors(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    signal = epics_signal_rw(str, "non-existent")
    with pytest.raises(NotConnected):
        await signal.connect(timeout=0.1)


def test_make_backend_fails_for_different_transports():
    read_pv = "test"
    write_pv = "pva://test"

    with pytest.raises(
        TypeError,
        match=f"Differing protocols: {read_pv} has EpicsProtocol.CA,"
        + f" {write_pv} has EpicsProtocol.PVA",
    ):
        epics_signal_rw(str, read_pv, write_pv)


def test_signal_helpers():
    read_write = epics_signal_rw(int, "ReadWrite")
    assert read_write._connector.backend.read_pv == "ReadWrite"
    assert read_write._connector.backend.write_pv == "ReadWrite"

    read_write_rbv_manual = epics_signal_rw(int, "ReadWrite_RBV", "ReadWrite")
    assert read_write_rbv_manual._connector.backend.read_pv == "ReadWrite_RBV"
    assert read_write_rbv_manual._connector.backend.write_pv == "ReadWrite"

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite")
    assert read_write_rbv._connector.backend.read_pv == "ReadWrite_RBV"
    assert read_write_rbv._connector.backend.write_pv == "ReadWrite"

    read_write_rbv_suffix = epics_signal_rw_rbv(int, "ReadWrite", read_suffix=":RBV")
    assert read_write_rbv_suffix._connector.backend.read_pv == "ReadWrite:RBV"
    assert read_write_rbv_suffix._connector.backend.write_pv == "ReadWrite"

    read_write_rbv_w_field = epics_signal_rw_rbv(int, "ReadWrite.VAL")
    assert read_write_rbv_w_field._connector.backend.read_pv == "ReadWrite_RBV.VAL"
    assert read_write_rbv_w_field._connector.backend.write_pv == "ReadWrite.VAL"

    read = epics_signal_r(int, "Read")
    assert read._connector.backend.read_pv == "Read"

    write = epics_signal_w(int, "Write")
    assert write._connector.backend.write_pv == "Write"

    execute = epics_signal_x("Execute")
    assert execute._connector.backend.write_pv == "Execute"


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_signals_created_for_prec_0_float_can_use_int(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv(protocol, "float_prec_0"))
    await sig.connect()


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_signals_created_for_not_prec_0_float_cannot_use_int(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv(protocol, "float_prec_1"))
    with pytest.raises(
        TypeError,
        match="float_prec_1 with inferred datatype float" ".* cannot be coerced to int",
    ):
        await sig.connect()


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_bool_works_for_mismatching_enums(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    pv_name = ioc_devices.get_pv(protocol, "bool")
    sig = epics_signal_rw(bool, pv_name, pv_name + "_unnamed")
    await sig.connect()


# @pytest.mark.skipif(os.name == "nt", reason="Hangs on windows for unknown reasons")
async def test_can_read_using_ophyd_async_then_ophyd(
    RE, ioc_devices: ExampleIocAndDevices
):
    ophyd_async_sig = epics_signal_rw(float, ioc_devices.get_pv("ca", "float_prec_1"))
    await ophyd_async_sig.connect()
    ophyd_signal = EpicsSignal(ioc_devices.get_pv("ca", "float_prec_0").split("://")[1])
    ophyd_signal.wait_for_connection(timeout=5)

    def my_plan():
        yield from bps.rd(ophyd_async_sig)
        yield from bps.rd(ophyd_signal)

    RE(my_plan())


def test_signal_module_emits_deprecation_warning():
    with pytest.deprecated_call():
        import ophyd_async.epics.signal  # noqa: F401


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_observe_ticking_signal_with_busy_loop(
    ioc_devices: ExampleIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv("ca", "ticking"))
    await sig.connect()

    recv = []

    async def watch():
        async for val in observe_value(sig, done_timeout=0.4):
            time.sleep(0.3)
            recv.append(val)

    start = time.time()

    with pytest.raises(asyncio.TimeoutError):
        await watch()
    assert time.time() - start == pytest.approx(0.6, abs=0.1)
    assert len(recv) == 2
    # Don't check values as CA and PVA have different algorithms for
    # dropping updates for slow callbacks
