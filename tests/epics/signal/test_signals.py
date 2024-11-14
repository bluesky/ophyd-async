import asyncio
import os
import random
import string
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import GenericAlias
from typing import Any, Literal
from unittest.mock import ANY

import bluesky.plan_stubs as bps
import numpy as np
import pytest
from aioca import purge_channel_caches
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine
from event_model import DataKey, Limits, LimitsRange
from ophyd.signal import EpicsSignal

from ophyd_async.core import (
    Array1D,
    NotConnected,
    SignalBackend,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
    T,
    Table,
    load_from_yaml,
    observe_value,
    save_to_yaml,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_signal_x,
)
from ophyd_async.epics.core._signal import _epics_signal_backend  # noqa: PLC2701

RECORDS = str(Path(__file__).parent / "test_records.db")
PV_PREFIX = "".join(random.choice(string.ascii_lowercase) for _ in range(12))


@dataclass
class IOC:
    process: subprocess.Popen
    protocol: Literal["ca", "pva"]

    async def make_backend(
        self, typ: type | None, suff: str, timeout=10.0
    ) -> SignalBackend:
        # Calculate the pv
        pv = f"{self.protocol}://{PV_PREFIX}:{self.protocol}:{suff}"
        # Make and connect the backend
        backend = _epics_signal_backend(typ, pv, pv)
        await backend.connect(timeout=timeout)
        return backend


# Use a module level fixture per protocol so it's fast to run tests. This means
# we need to add a record for every PV that we will modify in tests to stop
# tests interfering with each other
@pytest.fixture(scope="module", params=["pva", "ca"])
def ioc(request: pytest.FixtureRequest):
    protocol = request.param
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "epicscorelibs.ioc",
            "-m",
            f"P={PV_PREFIX}:{protocol}:",
            "-d",
            RECORDS,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )

    start_time = time.monotonic()
    line = ""
    while "iocRun: All initialization complete" not in line:
        if line:
            print(line)
        if time.monotonic() - start_time > 10:
            raise TimeoutError("IOC did not start in time")
        line = process.stdout.readline().strip()  # type: ignore

    yield IOC(process, protocol)

    # close backend caches before the event loop
    purge_channel_caches()
    try:
        print(process.communicate("exit()")[0])
    except ValueError:
        # Someone else already called communicate
        pass


def assert_types_are_equal(t_actual, t_expected, actual_value):
    expected_plain_type = getattr(t_expected, "__origin__", t_expected)
    if issubclass(expected_plain_type, np.ndarray):
        actual_plain_type = getattr(t_actual, "__origin__", t_actual)
        assert actual_plain_type == expected_plain_type
        actual_dtype_type = actual_value.dtype.type
        expected_dtype_type = t_expected.__args__[1].__args__[0]
        assert actual_dtype_type == expected_dtype_type
    elif (
        expected_plain_type is not str
        and not issubclass(expected_plain_type, Enum)
        and issubclass(expected_plain_type, Sequence)
    ):
        actual_plain_type = getattr(t_actual, "__origin__", t_actual)
        assert issubclass(actual_plain_type, expected_plain_type)
        assert len(actual_value) == 0 or isinstance(
            actual_value[0], t_expected.__args__[0]
        )
    else:
        assert t_actual == t_expected


class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.updates: asyncio.Queue[Reading] = asyncio.Queue()
        self.subscription = backend.set_callback(self.updates.put_nowait)

    async def assert_updates(self, expected_value, expected_type=None):
        expected_reading = {
            "value": expected_value,
            "timestamp": pytest.approx(time.time(), rel=0.1),
            "alarm_severity": 0,
        }
        backend_reading = await asyncio.wait_for(self.backend.get_reading(), timeout=5)
        backend_value = await asyncio.wait_for(self.backend.get_value(), timeout=5)
        update_reading = await asyncio.wait_for(self.updates.get(), timeout=5)
        update_value = update_reading["value"]

        assert update_value == expected_value == backend_value
        if expected_type:
            assert_types_are_equal(type(update_value), expected_type, update_value)
            assert_types_are_equal(type(backend_value), expected_type, backend_value)
        assert update_reading == expected_reading == backend_reading

    def close(self):
        self.backend.set_callback(None)


def _is_numpy_subclass(t):
    if t is None:
        return False
    plain_type = t.__origin__ if isinstance(t, GenericAlias) else t
    return issubclass(plain_type, np.ndarray)


async def assert_monitor_then_put(
    ioc: IOC,
    suffix: str,
    datakey: dict,
    initial_value: T,
    put_value: T,
    datatype: type[T] | None = None,
    check_type: bool | None = True,
):
    backend = await ioc.make_backend(datatype, suffix)
    # Make a monitor queue that will monitor for updates
    q = MonitorQueue(backend)
    try:
        # Check datakey
        source = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:{suffix}"
        assert dict(source=source, **datakey) == await backend.get_datakey(source)
        # Check initial value
        await q.assert_updates(
            pytest.approx(initial_value),
            datatype if check_type else None,
        )
        # Put to new value and check that
        await backend.put(put_value, wait=True)
        await q.assert_updates(
            pytest.approx(put_value), datatype if check_type else None
        )
    finally:
        q.close()


class MyEnum(StrictEnum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


class MySubsetEnum(SubsetEnum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


_metadata: dict[str, dict[str, dict[str, Any]]] = {
    "ca": {
        "boolean": {"units": ANY, "limits": ANY},
        "integer": {"units": ANY, "limits": ANY},
        "number": {"units": ANY, "limits": ANY, "precision": ANY},
        "enum": {},
        "string": {},
    },
    "pva": {
        "boolean": {},
        "integer": {"units": ANY, "precision": ANY, "limits": ANY},
        "number": {"units": ANY, "precision": ANY, "limits": ANY},
        "enum": {},
        "string": {"units": ANY, "precision": ANY, "limits": ANY},
    },
}


def datakey(protocol: str, suffix: str, value=None) -> DataKey:
    def get_internal_dtype(suffix: str) -> str:
        # uint32, [u]int64 backed by DBR_DOUBLE, have precision
        if "float" in suffix or "uint32" in suffix or "int64" in suffix:
            return "number"
        if "int" in suffix:
            return "integer"
        if "bool" in suffix:
            return "boolean"
        if "enum" in suffix:
            return "enum"
        return "string"

    def get_dtype(suffix: str) -> str:
        if suffix.endswith("a"):
            return "array"
        if "enum" in suffix:
            return "string"
        return get_internal_dtype(suffix)

    def get_dtype_numpy(suffix: str) -> str:  # type: ignore
        if "float32" in suffix:
            return "<f4"
        if "float" in suffix or "double" in suffix:
            return "<f8"  # Unless specifically float 32, use float 64
        if "bool" in suffix:
            return "|b1"
        if "int" in suffix:
            int_str = "|" if "8" in suffix else "<"
            int_str += "u" if "uint" in suffix else "i"
            if "8" in suffix:
                int_str += "1"
            elif "16" in suffix:
                int_str += "2"
            elif "32" in suffix:
                int_str += "4"
            elif "64" in suffix:
                int_str += "8"
            else:
                int_str += (
                    "4"
                    if os.name == "nt" and np.version.version.startswith("1.")
                    else "8"
                )
            return int_str
        if "str" in suffix or "enum" in suffix:
            return "|S40"

    dtype = get_dtype(suffix)
    dtype_numpy = get_dtype_numpy(suffix)

    d = {
        "dtype": dtype,
        "dtype_numpy": dtype_numpy,
        "shape": [len(value)] if dtype == "array" else [],  # type: ignore
    }
    if get_internal_dtype(suffix) == "enum":
        if issubclass(type(value), Enum):
            d["choices"] = [e.value for e in type(value)]  # type: ignore
        else:
            d["choices"] = list(value.choices)  # type: ignore

    d.update(_metadata[protocol].get(get_internal_dtype(suffix), {}))

    return d  # type: ignore


ls1 = "a string that is just longer than forty characters"
ls2 = "another string that is just longer than forty characters"


@pytest.mark.parametrize(
    "datatype, suffix, initial_value, put_value, supported_backends",
    [
        # python builtin scalars
        (int, "int", 42, 43, {"ca", "pva"}),
        (float, "float", 3.141, 43.5, {"ca", "pva"}),
        (str, "str", "hello", "goodbye", {"ca", "pva"}),
        (MyEnum, "enum", MyEnum.b, MyEnum.c, {"ca", "pva"}),
        # numpy arrays of numpy types
        (
            Array1D[np.int8],
            "int8a",
            [-128, 127],
            [-8, 3, 44],
            {"pva"},
        ),
        (
            Array1D[np.uint8],
            "uint8a",
            [0, 255],
            [218],
            {"ca", "pva"},
        ),
        (
            Array1D[np.int16],
            "int16a",
            [-32768, 32767],
            [-855],
            {"ca", "pva"},
        ),
        (
            Array1D[np.uint16],
            "uint16a",
            [0, 65535],
            [5666],
            {"pva"},
        ),
        (
            Array1D[np.int32],
            "int32a",
            [-2147483648, 2147483647],
            [-2],
            {"ca", "pva"},
        ),
        (
            Array1D[np.uint32],
            "uint32a",
            [0, 4294967295],
            [1022233],
            {"pva"},
        ),
        (
            Array1D[np.int64],
            "int64a",
            [-2147483649, 2147483648],
            [-3],
            {"pva"},
        ),
        (
            Array1D[np.uint64],
            "uint64a",
            [0, 4294967297],
            [995444],
            {"pva"},
        ),
        (
            Array1D[np.float32],
            "float32a",
            [0.000002, -123.123],
            [1.0],
            {"ca", "pva"},
        ),
        (
            Array1D[np.float64],
            "float64a",
            [0.1, -12345678.123],
            [0.2],
            {"ca", "pva"},
        ),
        (
            Sequence[str],
            "stra",
            ["five", "six", "seven"],
            ["nine", "ten"],
            {"pva", "ca"},
        ),
        # Can't do long strings until https://github.com/epics-base/pva2pva/issues/17
        # (str, "longstr", ls1, ls2),
        # (str, "longstr2.VAL$", ls1, ls2),
    ],
)
async def test_backend_get_put_monitor(
    ioc: IOC,
    datatype: type[T],
    suffix: str,
    initial_value: T,
    put_value: T,
    tmp_path: Path,
    supported_backends: set[str],
):
    # ca can't support all the types
    for backend in supported_backends:
        assert backend in ["ca", "pva"]
    if ioc.protocol not in supported_backends:
        return
    # With the given datatype, check we have the correct initial value and putting
    # works
    await assert_monitor_then_put(
        ioc,
        suffix,
        datakey(ioc.protocol, suffix, initial_value),  # type: ignore
        initial_value,
        put_value,
        datatype,
    )
    # With datatype guessed from CA/PVA, check we can set it back to the initial value
    await assert_monitor_then_put(
        ioc,
        suffix,
        datakey(ioc.protocol, suffix, put_value),  # type: ignore
        put_value,
        initial_value,
        datatype=None,
    )

    yaml_path = tmp_path / "test.yaml"
    save_to_yaml([{"test": put_value}], yaml_path)
    loaded = load_from_yaml(yaml_path)
    assert np.all(loaded[0]["test"] == put_value)


@pytest.mark.parametrize("suffix", ["bool", "bool_unnamed"])
async def test_bool_conversion_of_enum(ioc: IOC, suffix: str, tmp_path: Path) -> None:
    """Booleans are converted to Short Enumerations with values 0,1 as database does
    not support boolean natively.
    The flow of test_backend_get_put_monitor Gets a value with a dtype of None: we
    cannot tell the difference between an enum with 2 members and a boolean, so
    cannot get a DataKey that does not mutate form.
    This test otherwise performs the same.
    """
    # With the given datatype, check we have the correct initial value and putting
    # works
    await assert_monitor_then_put(
        ioc,
        suffix,
        datakey(ioc.protocol, suffix),
        True,
        False,
        bool,
    )
    # With datatype guessed from CA/PVA, check we can set it back to the initial value
    await assert_monitor_then_put(
        ioc,
        suffix,
        datakey(ioc.protocol, suffix, True),
        False,
        True,
        bool,
    )

    yaml_path = tmp_path / "test.yaml"
    save_to_yaml([{"test": False}], yaml_path)
    loaded = load_from_yaml(yaml_path)
    assert np.all(loaded[0]["test"] is False)


async def test_error_raised_on_disconnected_PV(ioc: IOC) -> None:
    if ioc.protocol == "pva":
        expected = "pva://Disconnect"
    elif ioc.protocol == "ca":
        expected = "ca://Disconnect"
    else:
        raise TypeError()
    backend = await ioc.make_backend(bool, "bool")
    signal = SignalRW(backend)
    # The below will work without error
    await signal.set(False)
    # Change the name of write_pv to mock disconnection
    backend.__setattr__("write_pv", "Disconnect")
    with pytest.raises(asyncio.TimeoutError, match=expected):
        await signal.set(True, timeout=0.1)


class BadEnum(StrictEnum):
    a = "Aaa"
    b = "B"
    c = "Ccc"


def test_enum_equality():
    """Check that we are allowed to replace the passed datatype enum from a signal with
    a version generated from the signal with at least all of the same values, but
    possibly more.
    """

    class GeneratedChoices(StrictEnum):
        a = "Aaa"
        b = "B"
        c = "Ccc"

    class ExtendedGeneratedChoices(StrictEnum):
        a = "Aaa"
        b = "B"
        c = "Ccc"
        d = "Ddd"

    for enum_class in (GeneratedChoices, ExtendedGeneratedChoices):
        assert BadEnum.a == enum_class.a
        assert BadEnum.a.value == enum_class.a
        assert BadEnum.a.value == enum_class.a.value
        assert BadEnum(enum_class.a) is BadEnum.a
        assert BadEnum(enum_class.a.value) is BadEnum.a
        assert not BadEnum == enum_class

    # We will always PUT BadEnum by String, and GET GeneratedChoices by index,
    # so shouldn't ever run across this from conversion code, but may occur if
    # casting returned values or passing as enum rather than value.
    with pytest.raises(ValueError):
        BadEnum(ExtendedGeneratedChoices.d)


class EnumNoString(Enum):
    a = "Aaa"


class SubsetEnumWrongChoices(SubsetEnum):
    a = "Aaa"
    b = "B"
    c = "Ccc"


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
    ],
)
async def test_backend_wrong_type_errors(ioc: IOC, typ, suff, errors):
    with pytest.raises(TypeError) as cm:
        await ioc.make_backend(typ, suff)
    for error in errors:
        assert error in str(cm.value)


async def test_backend_put_enum_string(ioc: IOC) -> None:
    backend = await ioc.make_backend(MyEnum, "enum2")
    # Don't do this in production code, but allow on CLI
    await backend.put("Ccc", wait=True)  # type: ignore
    assert MyEnum.c == await backend.get_value()


async def test_backend_enum_which_doesnt_inherit_string(ioc: IOC) -> None:
    with pytest.raises(TypeError):
        backend = await ioc.make_backend(EnumNoString, "enum2")
        await backend.put("Aaa", wait=True)


async def test_backend_get_setpoint(ioc: IOC) -> None:
    backend = await ioc.make_backend(MyEnum, "enum2")
    await backend.put("Ccc", wait=True)
    assert await backend.get_setpoint() == MyEnum.c


def approx_table(datatype: type[Table], table: Table):
    new_table = datatype(**table.model_dump())
    for k, v in new_table:
        if datatype is Table:
            setattr(new_table, k, pytest.approx(v))
        else:
            object.__setattr__(new_table, k, pytest.approx(v))
    return new_table


class MyTable(Table):
    bool: Array1D[np.bool_]
    int: Array1D[np.int32]
    float: Array1D[np.float64]
    str: Sequence[str]
    enum: Sequence[MyEnum]


async def test_pva_table(ioc: IOC) -> None:
    if ioc.protocol == "ca":
        # CA can't do tables
        return
    initial = MyTable(
        bool=np.array([False, False, True, True], np.bool_),
        int=np.array([1, 8, -9, 32], np.int32),
        float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        str=["Hello", "World", "Foo", "Bar"],
        enum=[MyEnum.a, MyEnum.b, MyEnum.a, MyEnum.c],
    )
    put = MyTable(
        bool=np.array([True, False], np.bool_),
        int=np.array([-5, 32], np.int32),
        float=np.array([8.5, -6.97], np.float64),
        str=["Hello", "Bat"],
        enum=[MyEnum.c, MyEnum.b],
    )
    # Make and connect the backend
    for t, i, p in [(MyTable, initial, put), (None, put, initial)]:
        backend = await ioc.make_backend(t, "table")
        # Make a monitor queue that will monitor for updates
        q = MonitorQueue(backend)
        try:
            # Check datakey
            dk = await backend.get_datakey("test-source")
            expected_dk = {
                "dtype": "array",
                "shape": [len(i)],
                "source": "test-source",
                "dtype_numpy": [
                    # natively bool fields are uint8, so if we don't provide a Table
                    # subclass to specify bool, that is what we get
                    ("bool", "|b1" if t else "|u1"),
                    ("int", "<i4"),
                    ("float", "<f8"),
                    ("str", "|S40"),
                    ("enum", "|S40"),
                ],
            }
            assert expected_dk == dk
            # Check initial value
            await q.assert_updates(approx_table(t or Table, i))
            # Put to new value and check that
            await backend.put(p, wait=True)
            await q.assert_updates(approx_table(t or Table, p))
        finally:
            q.close()


async def test_pva_ntdarray(ioc: IOC):
    if ioc.protocol == "ca":
        # CA can't do ndarray
        return

    put = np.array([1, 2, 3, 4, 5, 6], dtype=np.int64).reshape((2, 3))
    initial = np.zeros_like(put)

    backend = await ioc.make_backend(np.ndarray, "ntndarray")

    # Backdoor into the "raw" data underlying the NDArray in QSrv
    # not supporting direct writes to NDArray at the moment.
    raw_data_backend = await ioc.make_backend(Array1D[np.int64], "ntndarray:data")

    # Make a monitor queue that will monitor for updates
    for i, p in [(initial, put), (put, initial)]:
        with closing(MonitorQueue(backend)) as q:
            assert {
                "source": "test-source",
                "dtype": "array",
                "dtype_numpy": "<i8",
                "shape": [2, 3],
            } == await backend.get_datakey("test-source")
            # Check initial value
            await q.assert_updates(pytest.approx(i))
            await raw_data_backend.put(p.flatten(), wait=True)
            await q.assert_updates(pytest.approx(p))


async def test_writing_to_ndarray_raises_typeerror(ioc: IOC):
    if ioc.protocol == "ca":
        # CA can't do ndarray
        return

    backend = await ioc.make_backend(np.ndarray, "ntndarray")

    with pytest.raises(TypeError):
        await backend.put(np.zeros((6,), dtype=np.int64), wait=True)


async def test_non_existent_errors(ioc: IOC):
    with pytest.raises(NotConnected):
        await ioc.make_backend(str, "non-existent", timeout=0.1)


def test_make_backend_fails_for_different_transports():
    read_pv = "test"
    write_pv = "pva://test"

    with pytest.raises(TypeError) as err:
        epics_signal_rw(str, read_pv, write_pv)
        assert (
            err.args[0]
            == f"Differing transports: {read_pv} has EpicsTransport.ca,"
            + " {write_pv} has EpicsTransport.pva"
        )


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

    read = epics_signal_r(int, "Read")
    assert read._connector.backend.read_pv == "Read"

    write = epics_signal_w(int, "Write")
    assert write._connector.backend.write_pv == "Write"

    execute = epics_signal_x("Execute")
    assert execute._connector.backend.write_pv == "Execute"


async def test_str_enum_returns_enum(ioc: IOC):
    await ioc.make_backend(MyEnum, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"

    sig = epics_signal_rw(MyEnum, pv_name)
    await sig.connect()
    val = await sig.get_value()
    assert repr(val) == "<MyEnum.b: 'Bbb'>"
    assert val is MyEnum.b
    assert val == "Bbb"


async def test_str_datatype_in_mbbo(ioc: IOC):
    backend = await ioc.make_backend(MyEnum, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"
    sig = epics_signal_rw(str, pv_name)
    datakey = await backend.get_datakey(sig.source)
    assert datakey["choices"] == ["Aaa", "Bbb", "Ccc"]
    await sig.connect()
    description = await sig.describe()
    assert description[""]["choices"] == ["Aaa", "Bbb", "Ccc"]
    val = await sig.get_value()
    assert val == "Bbb"


async def test_runtime_enum_returns_str(ioc: IOC):
    await ioc.make_backend(MySubsetEnum, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"
    sig = epics_signal_rw(MySubsetEnum, pv_name)

    await sig.connect()
    val = await sig.get_value()
    assert val == "Bbb"


async def test_signal_returns_units_and_precision(ioc: IOC):
    await ioc.make_backend(float, "float")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:float"

    sig = epics_signal_rw(float, pv_name)
    await sig.connect()
    datakey = (await sig.describe())[""]
    assert datakey["units"] == "mm"
    assert datakey["precision"] == 1


async def test_signal_not_return_none_units_and_precision(ioc: IOC):
    await ioc.make_backend(str, "str")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:str"

    sig = epics_signal_rw(str, pv_name)
    await sig.connect()
    datakey = (await sig.describe())[""]
    assert not hasattr(datakey, "units")
    assert not hasattr(datakey, "precision")


async def test_signal_returns_limits(ioc: IOC):
    await ioc.make_backend(int, "int")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:int"

    expected_limits = Limits(
        # LOW, HIGH
        warning=LimitsRange(low=5.0, high=96.0),
        # DRVL, DRVH
        control=LimitsRange(low=10.0, high=90.0),
        # LOPR, HOPR
        display=LimitsRange(low=0.0, high=100.0),
        # LOLO, HIHI
        alarm=LimitsRange(low=2.0, high=98.0),
    )

    sig = epics_signal_rw(int, pv_name)
    await sig.connect()
    limits = (await sig.describe())[""]["limits"]
    assert limits == expected_limits


async def test_signal_returns_partial_limits(ioc: IOC):
    await ioc.make_backend(int, "partialint")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:partialint"

    expected_limits = Limits(
        # LOLO, HIHI
        alarm=LimitsRange(low=2.0, high=98.0),
        # DRVL, DRVH
        control=LimitsRange(low=10.0, high=90.0),
        # LOPR, HOPR
        display=LimitsRange(low=0.0, high=100.0),
    )
    if ioc.protocol == "ca":
        # HSV, LSV not set, but still present for CA
        expected_limits["warning"] = LimitsRange(low=0, high=0)

    sig = epics_signal_rw(int, pv_name)
    await sig.connect()
    limits = (await sig.describe())[""]["limits"]
    assert limits == expected_limits


async def test_signal_returns_warning_and_partial_limits(ioc: IOC):
    await ioc.make_backend(int, "lessint")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:lessint"

    expected_limits = Limits(
        # control = display if DRVL, DRVH not set
        control=LimitsRange(low=0.0, high=100.0),
        # LOPR, HOPR
        display=LimitsRange(low=0.0, high=100.0),
        # LOW, HIGH
        warning=LimitsRange(low=2.0, high=98.0),
    )
    if ioc.protocol == "ca":
        # HSV, LSV not set, but still present for CA
        expected_limits["alarm"] = LimitsRange(low=0, high=0)

    sig = epics_signal_rw(int, pv_name)
    await sig.connect()
    limits = (await sig.describe())[""]["limits"]
    assert limits == expected_limits


async def test_signal_not_return_no_limits(ioc: IOC):
    await ioc.make_backend(MyEnum, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"
    sig = epics_signal_rw(MyEnum, pv_name)
    await sig.connect()
    datakey = (await sig.describe())[""]
    assert not hasattr(datakey, "limits")


async def test_signals_created_for_prec_0_float_can_use_int(ioc: IOC):
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:float_prec_0"
    sig = epics_signal_rw(int, pv_name)
    await sig.connect()


async def test_signals_created_for_not_prec_0_float_cannot_use_int(ioc: IOC):
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:float_prec_1"
    sig = epics_signal_rw(int, pv_name)
    with pytest.raises(
        TypeError,
        match=f"{ioc.protocol}:float_prec_1 with inferred datatype float"
        ".* cannot be coerced to int",
    ):
        await sig.connect()


async def test_bool_works_for_mismatching_enums(ioc: IOC):
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:bool"
    sig = epics_signal_rw(bool, pv_name, pv_name + "_unnamed")
    await sig.connect()


@pytest.mark.skipif(os.name == "nt", reason="Hangs on windows for unknown reasons")
async def test_can_read_using_ophyd_async_then_ophyd(ioc: IOC):
    oa_read = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:float_prec_1"
    ophyd_read = f"{PV_PREFIX}:{ioc.protocol}:float_prec_0"

    ophyd_async_sig = epics_signal_rw(float, oa_read)
    await ophyd_async_sig.connect()
    ophyd_signal = EpicsSignal(ophyd_read)
    ophyd_signal.wait_for_connection(timeout=5)

    RE = RunEngine()

    def my_plan():
        yield from bps.rd(ophyd_async_sig)
        yield from bps.rd(ophyd_signal)

    RE(my_plan())


def test_signal_module_emits_deprecation_warning():
    with pytest.deprecated_call():
        import ophyd_async.epics.signal  # noqa: F401


async def test_observe_ticking_signal_with_busy_loop(ioc: IOC):
    sig = SignalR(await ioc.make_backend(int, "ticking"))
    recv = []

    async def watch():
        async for val in observe_value(sig):
            time.sleep(0.15)
            recv.append(val)

    start = time.time()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(watch(), timeout=0.2)
    assert time.time() - start == pytest.approx(0.3, abs=0.05)
    assert len(recv) == 2
    # Don't check values as CA and PVA have different algorithms for
    # dropping updates for slow callbacks
