import asyncio
import random
import re
import string
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Sequence, Tuple, Type, TypedDict
from unittest.mock import ANY

import numpy as np
import numpy.typing as npt
import pytest
from aioca import CANothing, purge_channel_caches
from bluesky.protocols import Descriptor, Reading

from ophyd_async.core import SignalBackend, T, get_dtype, load_from_yaml, save_to_yaml
from ophyd_async.core.utils import NotConnected
from ophyd_async.epics.signal._epics_transport import EpicsTransport
from ophyd_async.epics.signal.signal import (
    _make_backend,
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_signal_x,
)

RECORDS = str(Path(__file__).parent / "test_records.db")
PV_PREFIX = "".join(random.choice(string.ascii_lowercase) for _ in range(12))


@dataclass
class IOC:
    process: subprocess.Popen
    protocol: Literal["ca", "pva"]

    async def make_backend(
        self, typ: Optional[Type], suff: str, connect=True
    ) -> SignalBackend:
        # Calculate the pv
        pv = f"{PV_PREFIX}:{self.protocol}:{suff}"
        # Make and connect the backend
        cls = EpicsTransport[self.protocol].value
        backend = cls(typ, pv, pv)
        if connect:
            await asyncio.wait_for(backend.connect(), 10)
        return backend


# Use a module level fixture per protocol so it's fast to run tests. This means
# we need to add a record for every PV that we will modify in tests to stop
# tests interfering with each other
@pytest.fixture(scope="module", params=["pva", "ca"])
def ioc(request):
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
    while "iocRun: All initialization complete" not in (
        process.stdout.readline().strip()
    ):
        if time.monotonic() - start_time > 10:
            raise TimeoutError("IOC did not start in time")

    yield IOC(process, protocol)

    # close backend caches before the event loop
    purge_channel_caches()
    try:
        print(process.communicate("exit")[0])
    except ValueError:
        # Someone else already called communicate
        pass


class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.subscription = backend.set_callback(self.add_reading_value)
        self.updates: asyncio.Queue[Tuple[Reading, Any]] = asyncio.Queue()

    def add_reading_value(self, reading: Reading, value):
        self.updates.put_nowait((reading, value))

    async def assert_updates(self, expected_value):
        expected_reading = {
            "value": expected_value,
            "timestamp": pytest.approx(time.time(), rel=0.1),
            "alarm_severity": 0,
        }
        backend_reading = await asyncio.wait_for(self.backend.get_reading(), timeout=5)
        reading, value = await asyncio.wait_for(self.updates.get(), timeout=5)
        backend_value = await asyncio.wait_for(self.backend.get_value(), timeout=5)

        assert value == expected_value == backend_value
        assert reading == expected_reading == backend_reading

    def close(self):
        self.backend.set_callback(None)


async def assert_monitor_then_put(
    ioc: IOC,
    suffix: str,
    descriptor: dict,
    initial_value: T,
    put_value: T,
    datatype: Optional[Type[T]] = None,
):
    backend = await ioc.make_backend(datatype, suffix)
    # Make a monitor queue that will monitor for updates
    q = MonitorQueue(backend)
    try:
        # Check descriptor
        source = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:{suffix}"
        assert (
            dict(source=source, **descriptor).items()
            <= (await backend.get_descriptor()).items()
        )
        # Check initial value
        await q.assert_updates(pytest.approx(initial_value))
        # Put to new value and check that
        await backend.put(put_value)
        await q.assert_updates(pytest.approx(put_value))
    finally:
        q.close()


async def put_error(
    ioc: IOC,
    suffix: str,
    put_value: T,
    datatype: Optional[Type[T]] = None,
):
    backend = await ioc.make_backend(datatype, suffix)
    # The below will work without error
    await backend.put(put_value)
    # Change the name of write_pv to mock disconnection
    backend.__setattr__("write_pv", "Disconnect")
    await backend.put(put_value, timeout=3)


class MyEnum(str, Enum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


_common_metadata = {
    "units": ANY,
    "upper_disp_limit": ANY,
    "lower_disp_limit": ANY,
    "upper_ctrl_limit": ANY,
    "lower_ctrl_limit": ANY,
}

_metadata: Dict[str, Dict[str, Any]] = {
    "string": {"timestamp": ANY},
    "integer": _common_metadata,
    "number": {**_common_metadata, "precision": ANY},
    "enum": {},
}


def descriptor(protocol: str, suffix: str, value=None) -> Descriptor:
    def get_internal_dtype(suffix: str) -> str:
        if "int" in suffix or "bool" in suffix:
            return "integer"
        if "float" in suffix:
            return "number"
        if "enum" in suffix:
            return "enum"
        return "string"

    def get_dtype(suffix: str) -> str:
        if suffix.endswith("a"):
            return "array"
        if "enum" in suffix:
            return "string"
        return get_internal_dtype(suffix)

    dtype = get_dtype(suffix)

    d = dict(dtype=dtype, shape=[len(value)] if dtype == "array" else [])
    if get_internal_dtype(suffix) == "enum":
        d["choices"] = [e.value for e in type(value)]

    if protocol == "ca":
        d.update(_metadata[get_internal_dtype(suffix)])

    return d


ls1 = "a string that is just longer than forty characters"
ls2 = "another string that is just longer than forty characters"

ca_dtype_mapping = {
    np.int8: np.uint8,
    np.uint16: np.int32,
    np.uint32: np.float64,
    np.int64: np.float64,
    np.uint64: np.float64,
}


@pytest.mark.parametrize(
    "datatype, suffix, initial_value, put_value",
    [
        (int, "int", 42, 43),
        (float, "float", 3.141, 43.5),
        (str, "str", "hello", "goodbye"),
        (MyEnum, "enum", MyEnum.b, MyEnum.c),
        (npt.NDArray[np.int8], "int8a", [-128, 127], [-8, 3, 44]),
        (npt.NDArray[np.uint8], "uint8a", [0, 255], [218]),
        (npt.NDArray[np.int16], "int16a", [-32768, 32767], [-855]),
        (npt.NDArray[np.uint16], "uint16a", [0, 65535], [5666]),
        (npt.NDArray[np.int32], "int32a", [-2147483648, 2147483647], [-2]),
        (npt.NDArray[np.uint32], "uint32a", [0, 4294967295], [1022233]),
        (npt.NDArray[np.int64], "int64a", [-2147483649, 2147483648], [-3]),
        (npt.NDArray[np.uint64], "uint64a", [0, 4294967297], [995444]),
        (npt.NDArray[np.float32], "float32a", [0.000002, -123.123], [1.0]),
        (npt.NDArray[np.float64], "float64a", [0.1, -12345678.123], [0.2]),
        (Sequence[str], "stra", ["five", "six", "seven"], ["nine", "ten"]),
        # Can't do long strings until https://github.com/epics-base/pva2pva/issues/17
        # (str, "longstr", ls1, ls2),
        # (str, "longstr2.VAL$", ls1, ls2),
    ],
)
async def test_backend_get_put_monitor(
    ioc: IOC,
    datatype: Type[T],
    suffix: str,
    initial_value: T,
    put_value: T,
    tmp_path,
):
    # ca can't support all the types
    dtype = get_dtype(datatype)
    if ioc.protocol == "ca" and dtype and dtype.type in ca_dtype_mapping:
        if dtype == np.int8:
            # CA maps uint8 onto int8 rather than upcasting, so we need to change
            # initial array
            initial_value, put_value = [  # type: ignore
                np.array(x).astype(np.uint8) for x in (initial_value, put_value)
            ]
        datatype = npt.NDArray[ca_dtype_mapping[dtype.type]]  # type: ignore
    # With the given datatype, check we have the correct initial value and putting
    # works
    await assert_monitor_then_put(
        ioc,
        suffix,
        descriptor(ioc.protocol, suffix, initial_value),
        initial_value,
        put_value,
        datatype,
    )
    # With datatype guessed from CA/PVA, check we can set it back to the initial value
    await assert_monitor_then_put(
        ioc,
        suffix,
        descriptor(ioc.protocol, suffix, put_value),
        put_value,
        initial_value,
        datatype=None,
    )

    yaml_path = tmp_path / "test.yaml"
    save_to_yaml([{"test": put_value}], yaml_path)
    loaded = load_from_yaml(yaml_path)
    assert np.all(loaded[0]["test"] == put_value)


@pytest.mark.parametrize("suffix", ["bool", "bool_unnamed"])
async def test_bool_conversion_of_enum(ioc: IOC, suffix: str) -> None:
    await assert_monitor_then_put(
        ioc,
        suffix=suffix,
        descriptor=descriptor(ioc.protocol, "bool"),
        initial_value=True,
        put_value=False,
        datatype=bool,
    )


async def test_error_raised_on_disconnected_PV(ioc: IOC) -> None:
    if ioc.protocol == "pva":
        err = NotConnected
        expected = "pva://Disconnect"
    elif ioc.protocol == "ca":
        err = CANothing
        expected = "Disconnect: User specified timeout on IO operation expired"
    with pytest.raises(err, match=expected):
        await put_error(
            ioc,
            suffix="bool",
            put_value=False,
            datatype=bool,
        )


class BadEnum(str, Enum):
    a = "Aaa"
    b = "B"
    c = "Ccc"


def test_enum_equality():
    """Check that we are allowed to replace the passed datatype enum from a signal with
    a version generated from the signal with at least all of the same values, but
    possibly more.
    """

    class GeneratedChoices(str, Enum):
        a = "Aaa"
        b = "B"
        c = "Ccc"

    class ExtendedGeneratedChoices(str, Enum):
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


@pytest.mark.parametrize(
    "typ, suff, error",
    [
        (
            BadEnum,
            "enum",
            (
                "has choices ('Aaa', 'Bbb', 'Ccc'), which do not match "
                "<enum 'BadEnum'>, which has ('Aaa', 'B', 'Ccc')"
            ),
        ),
        (int, "str", "has type str not int"),
        (str, "float", "has type float not str"),
        (str, "stra", "has type [str] not str"),
        (int, "uint8a", "has type [uint8] not int"),
        (float, "enum", "is type Enum but doesn't inherit from String"),
        (npt.NDArray[np.int32], "float64a", "has type [float64] not [int32]"),
    ],
)
async def test_backend_wrong_type_errors(ioc: IOC, typ, suff, error):
    with pytest.raises(
        TypeError, match=re.escape(f"{PV_PREFIX}:{ioc.protocol}:{suff} {error}")
    ):
        await ioc.make_backend(typ, suff)


async def test_backend_put_enum_string(ioc: IOC) -> None:
    backend = await ioc.make_backend(MyEnum, "enum2")
    # Don't do this in production code, but allow on CLI
    await backend.put("Ccc")  # type: ignore
    assert MyEnum.c == await backend.get_value()


async def test_backend_enum_which_doesnt_inherit_string(ioc: IOC) -> None:
    with pytest.raises(TypeError):
        backend = await ioc.make_backend(EnumNoString, "enum2")
        await backend.put("Aaa")


async def test_backend_get_setpoint(ioc: IOC) -> None:
    backend = await ioc.make_backend(MyEnum, "enum2")
    await backend.put("Ccc")
    assert await backend.get_setpoint() == MyEnum.c


def approx_table(table):
    return {k: pytest.approx(v) for k, v in table.items()}


class MyTable(TypedDict):
    bool: npt.NDArray[np.bool_]
    int: npt.NDArray[np.int32]
    float: npt.NDArray[np.float64]
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
    # TODO: what should this be for a variable length table?
    descriptor = {"dtype": "object", "shape": []}
    # Make and connect the backend
    for t, i, p in [(MyTable, initial, put), (None, put, initial)]:
        backend = await ioc.make_backend(t, "table")
        # Make a monitor queue that will monitor for updates
        q = MonitorQueue(backend)
        try:
            # Check descriptor
            dict(source=backend.source, **descriptor).items() <= (
                await backend.get_descriptor()
            ).items()

            # Check initial value
            await q.assert_updates(approx_table(i))
            # Put to new value and check that
            await backend.put(p)
            await q.assert_updates(approx_table(p))
        finally:
            q.close()


async def test_pvi_structure(ioc: IOC) -> None:
    if ioc.protocol == "ca":
        # CA can't do structure
        return
    # Make and connect the backend
    backend = await ioc.make_backend(Dict[str, Any], "pvi")

    # Make a monitor queue that will monitor for updates
    q = MonitorQueue(backend)

    expected = {
        "pvi": {
            "width": {
                "rw": f"{PV_PREFIX}:{ioc.protocol}:width",
            },
            "height": {
                "rw": f"{PV_PREFIX}:{ioc.protocol}:height",
            },
        },
        "record": ANY,
    }

    try:
        # Check descriptor
        with pytest.raises(NotImplementedError):
            await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(expected)
        await backend.get_value()

    finally:
        q.close()


async def test_pva_ntdarray(ioc: IOC):
    if ioc.protocol == "ca":
        # CA can't do ndarray
        return

    put = np.array([1, 2, 3, 4, 5, 6], dtype=np.int64).reshape((2, 3))
    initial = np.zeros_like(put)

    backend = await ioc.make_backend(npt.NDArray[np.int64], "ntndarray")

    # Backdoor into the "raw" data underlying the NDArray in QSrv
    # not supporting direct writes to NDArray at the moment.
    raw_data_backend = await ioc.make_backend(npt.NDArray[np.int64], "ntndarray:data")

    # Make a monitor queue that will monitor for updates
    for i, p in [(initial, put), (put, initial)]:
        with closing(MonitorQueue(backend)) as q:
            assert {
                "source": "test-source",
                "dtype": "array",
                "shape": [2, 3],
            }.items() <= (await backend.get_descriptor()).items()
            # Check initial value
            await q.assert_updates(pytest.approx(i))
            await raw_data_backend.put(p.flatten())
            await q.assert_updates(pytest.approx(p))


async def test_writing_to_ndarray_raises_typeerror(ioc: IOC):
    if ioc.protocol == "ca":
        # CA can't do ndarray
        return

    backend = await ioc.make_backend(npt.NDArray[np.int64], "ntndarray")

    with pytest.raises(TypeError):
        await backend.put(np.zeros((6,), dtype=np.int64))


async def test_non_existent_errors(ioc: IOC):
    backend = await ioc.make_backend(str, "non-existent", connect=False)
    # Can't use asyncio.wait_for on python3.8 because of
    # https://github.com/python/cpython/issues/84787
    with pytest.raises(NotConnected):
        await backend.connect(timeout=0.1)


def test_make_backend_fails_for_different_transports():
    read_pv = "test"
    write_pv = "pva://test"

    with pytest.raises(TypeError) as err:
        _make_backend(str, read_pv, write_pv)
        assert err.args[0] == f"Differing transports: {read_pv} has EpicsTransport.ca,"
        +" {write_pv} has EpicsTransport.pva"


def test_signal_helpers():
    read_write = epics_signal_rw(int, "ReadWrite")
    assert read_write._backend.read_pv == "ReadWrite"
    assert read_write._backend.write_pv == "ReadWrite"

    read_write_rbv_manual = epics_signal_rw(int, "ReadWrite_RBV", "ReadWrite")
    assert read_write_rbv_manual._backend.read_pv == "ReadWrite_RBV"
    assert read_write_rbv_manual._backend.write_pv == "ReadWrite"

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite")
    assert read_write_rbv._backend.read_pv == "ReadWrite_RBV"
    assert read_write_rbv._backend.write_pv == "ReadWrite"

    read_write_rbv_suffix = epics_signal_rw_rbv(int, "ReadWrite", read_suffix=":RBV")
    assert read_write_rbv_suffix._backend.read_pv == "ReadWrite:RBV"
    assert read_write_rbv_suffix._backend.write_pv == "ReadWrite"

    read = epics_signal_r(int, "Read")
    assert read._backend.read_pv == "Read"

    write = epics_signal_w(int, "Write")
    assert write._backend.write_pv == "Write"

    execute = epics_signal_x("Execute")
    assert execute._backend.write_pv == "Execute"


async def test_str_enum_returns_enum(ioc: IOC):
    await ioc.make_backend(MyEnum, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"

    sig = epics_signal_rw(MyEnum, pv_name)
    await sig.connect()
    val = await sig.get_value()
    assert repr(val) == "<MyEnum.b: 'Bbb'>"
    assert val is MyEnum.b
    assert val == "Bbb"


async def test_str_returns_enum(ioc: IOC):
    await ioc.make_backend(str, "enum")
    pv_name = f"{ioc.protocol}://{PV_PREFIX}:{ioc.protocol}:enum"

    sig = epics_signal_rw(str, pv_name)
    await sig.connect()
    val = await sig.get_value()
    assert val == MyEnum.b
    assert val == "Bbb"
    assert val is not MyEnum.b
