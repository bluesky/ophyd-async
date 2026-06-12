import asyncio
import os
import typing
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import numpy as np
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    Array1D,
    SoftSignalBackend,
    StrictEnum,
    soft_signal_rw,
)
from ophyd_async.testing import ExampleEnum, ExampleTable, MonitorQueue

T = TypeVar("T")


class MyEnum(StrictEnum):
    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


def integer_d(value):
    return {"dtype": "integer", "shape": []}


def number_d(value):
    return {"dtype": "number", "shape": []}


def string_d(value):
    return {"dtype": "string", "shape": []}


def enum_d(value):
    return {"dtype": "string", "shape": [], "choices": ["Aaa", "Bbb", "Ccc"]}


def waveform_d(value):
    return {"dtype": "array", "shape": [len(value)]}


def enumwf_d(value):
    return {"dtype": "array", "shape": [len(value)], "choices": ["Aaa", "Bbb", "Ccc"]}


def table_d(value):
    return {"dtype": "array", "shape": [len(value)]}


# Can be removed once numpy >=2 is pinned.
scalar_int_dtype = (
    "<i4" if os.name == "nt" and np.version.version.startswith("1.") else "<i8"
)


@pytest.mark.parametrize(
    "datatype, initial_value, put_value, descriptor, dtype_numpy",
    [
        (int, 0, 43, integer_d, scalar_int_dtype),
        (float, 0.0, 43.5, number_d, "<f8"),
        (str, "", "goodbye", string_d, "|S40"),
        (MyEnum, MyEnum.A, MyEnum.C, enum_d, "|S40"),
        (Array1D[np.int8], np.array([]), np.array([-8, 3, 44]), waveform_d, "|i1"),
        (Array1D[np.uint8], np.array([]), np.array([218]), waveform_d, "|u1"),
        (Array1D[np.int16], np.array([]), np.array([-855]), waveform_d, "<i2"),
        (Array1D[np.uint16], np.array([]), np.array([5666]), waveform_d, "<u2"),
        (Array1D[np.int32], np.array([]), np.array([-2]), waveform_d, "<i4"),
        (Array1D[np.uint32], np.array([]), np.array([1022233]), waveform_d, "<u4"),
        (Array1D[np.int64], np.array([]), np.array([-3]), waveform_d, "<i8"),
        (Array1D[np.uint64], np.array([]), np.array([995444]), waveform_d, "<u8"),
        (Array1D[np.float32], np.array([]), np.array([1.0]), waveform_d, "<f4"),
        (Array1D[np.float64], np.array([]), np.array([0.2]), waveform_d, "<f8"),
        (Sequence[str], [], ["nine", "ten"], waveform_d, "|S40"),
        (Sequence[MyEnum], [], [MyEnum.A, MyEnum.B], enumwf_d, "|S40"),
        (typing.Sequence[str], [], ["nine", "ten"], waveform_d, "|S40"),
        (typing.Sequence[MyEnum], [], [MyEnum.A, MyEnum.B], enumwf_d, "|S40"),
        (
            ExampleTable,
            ExampleTable(
                a_bool=np.array([]),
                a_int=np.array([]),
                a_float=np.array([]),
                a_str=[],
                a_enum=[],
            ),
            ExampleTable(
                a_bool=np.array([True]),
                a_int=np.array([525]),
                a_float=np.array([3.14]),
                a_str=["pi"],
                a_enum=[ExampleEnum.A],
            ),
            table_d,
            [
                ("a_bool", "|b1"),
                ("a_int", "<i4"),
                ("a_float", "<f8"),
                ("a_str", "|S40"),
                ("a_enum", "|S40"),
            ],
        ),
    ],
)
async def test_soft_signal_backend_get_put_monitor(
    datatype: type[T],
    initial_value: T,
    put_value: T,
    descriptor: Callable[[Any], dict],
    dtype_numpy: str,
):
    signal = soft_signal_rw(datatype, initial_value)
    await signal.connect()
    backend = signal._connector.backend
    with MonitorQueue(signal) as q:
        # Check descriptor
        source = "soft://test"
        # Add expected dtype_numpy to descriptor
        assert dict(
            source=source, **descriptor(initial_value), dtype_numpy=dtype_numpy
        ) == await backend.get_datakey(source)
        await q.assert_updates(initial_value)

        # Put to new value and check that
        await backend.put(put_value)
        await q.assert_updates(put_value)


async def test_soft_signal_backend_enum_value_equivalence():
    soft_backend = SoftSignalBackend(MyEnum)
    await soft_backend.connect(timeout=1)
    assert (await soft_backend.get_value()) is MyEnum.A
    await soft_backend.put(MyEnum.B)
    assert (await soft_backend.get_value()) is MyEnum.B


async def test_soft_signal_backend_set_callback():
    soft_backend = SoftSignalBackend(Array1D[np.float64])
    updates: asyncio.Queue[Reading] = asyncio.Queue()
    # set a callback, so that the subsequent set will fail
    soft_backend.set_callback(updates.put_nowait)
    assert soft_backend.callback is not None
    with pytest.raises(
        RuntimeError, match="Cannot set a callback when one is already set"
    ):
        soft_backend.set_callback(updates.put_nowait)
    soft_backend.set_callback(None)
    assert soft_backend.callback is None


async def test_soft_signal_backend_with_numpy_typing():
    soft_backend = SoftSignalBackend(Array1D[np.float64])
    await soft_backend.connect(timeout=1)
    await soft_backend.put(np.array([1, 2]))
    array = await soft_backend.get_value()
    assert array.shape == (2,)
    assert array[0] == 1


async def test_soft_signal_descriptor_fails_for_invalid_class():
    class MyClass:
        def __init__(self) -> None:
            pass

    with pytest.raises(TypeError):
        SoftSignalBackend(MyClass)


async def test_soft_signal_descriptor_with_metadata():
    soft_signal = soft_signal_rw(int, 0, units="mm", precision=0)
    await soft_signal.connect()
    datakey = await soft_signal.describe()
    assert datakey[""]["units"] == "mm"
    assert datakey[""]["precision"] == 0

    soft_signal = soft_signal_rw(int, units="")
    await soft_signal.connect()
    datakey = await soft_signal.describe()
    assert datakey[""]["units"] == ""
    assert not hasattr(datakey[""], "precision")


async def test_soft_signal_descriptor_with_no_metadata_not_passed():
    soft_signal = soft_signal_rw(int)
    await soft_signal.connect()
    datakey = await soft_signal.describe()
    assert not hasattr(datakey[""], "units")
    assert not hasattr(datakey[""], "precision")


async def test_soft_signal_coerces_numpy_types():
    soft_signal = soft_signal_rw(float)
    await soft_signal.connect()
    assert await soft_signal.get_value() == 0.0
    assert type(await soft_signal.get_value()) is float
    await soft_signal.set(np.float64(1.1))
    assert await soft_signal.get_value() == 1.1
    assert type(await soft_signal.get_value()) is float
    soft_signal._connector.backend.set_value(np.float64(2.2))
    assert await soft_signal.get_value() == 2.2
    assert type(await soft_signal.get_value()) is float


async def test_soft_signal_backend_getter():
    store = [42.0]
    backend = SoftSignalBackend(float, getter=lambda: store[0])
    await backend.connect(timeout=1)
    assert await backend.get_value() == 42.0
    store[0] = 99.0
    assert await backend.get_value() == 99.0


async def test_soft_signal_backend_async_getter():
    store = [42.0]

    async def getter():
        return store[0]

    backend = SoftSignalBackend(float, getter=getter)
    await backend.connect(timeout=1)
    store[0] = 99.0
    assert await backend.get_value() == 99.0


async def test_soft_signal_backend_getter_updates_reading():
    store = [1.0]
    backend = SoftSignalBackend(float, getter=lambda: store[0])
    await backend.connect(timeout=1)
    store[0] = 2.0
    reading = await backend.get_reading()
    assert reading["value"] == 2.0


async def test_soft_signal_backend_getter_does_not_affect_setpoint():
    store = [1.0]
    backend = SoftSignalBackend(float, getter=lambda: store[0])
    await backend.connect(timeout=1)
    await backend.put(5.0)
    store[0] = 99.0
    assert await backend.get_setpoint() == 5.0
    assert await backend.get_value() == 99.0


async def test_soft_signal_backend_setter_homogeneous_types():
    store = [0.0]

    def setter(v):
        store[0] = v

    backend = SoftSignalBackend(float, setter=setter)
    await backend.connect(timeout=1)
    await backend.put(7.0)
    assert store[0] == 7.0


async def test_soft_signal_backend_setter_heterogeneous_types():
    counts_written = []

    def counts_setter(counts: int) -> float:
        counts_written.append(counts)
        return counts * 0.01

    backend = SoftSignalBackend(float, setter=counts_setter)
    await backend.connect(timeout=1)
    await backend.put(1000)
    assert counts_written == [1000]
    assert await backend.get_value() == pytest.approx(10.0)


async def test_soft_signal_backend_async_setter_heterogeneous_types():
    counts_written = []

    async def counts_setter(counts: int) -> float:
        counts_written.append(counts)
        return counts * 0.01

    backend = SoftSignalBackend(float, setter=counts_setter)
    await backend.connect(timeout=1)
    await backend.put(500)
    assert counts_written == [500]
    assert await backend.get_value() == pytest.approx(5.0)


async def test_soft_signal_backend_setter_heterogeneous_none_return_with_getter():
    store = [0.0]
    commands = []

    def command_setter(cmd: str) -> None:
        commands.append(cmd)
        store[0] = float(cmd.split("=")[1])

    backend = SoftSignalBackend(float, setter=command_setter, getter=lambda: store[0])
    await backend.connect(timeout=1)
    await backend.put("pos=42.5")
    assert commands == ["pos=42.5"]
    assert await backend.get_value() == pytest.approx(42.5)


async def test_soft_signal_backend_setter_heterogeneous_none_return_without_getter():
    received = []

    def int_setter(v: int) -> None:
        received.append(v)

    backend = SoftSignalBackend(float, setter=int_setter)
    await backend.connect(timeout=1)
    await backend.put(42)
    assert received == [42]
    assert await backend.get_value() == pytest.approx(42.0)


async def test_soft_signal_backend_async_setter():
    store = [0.0]

    async def setter(v):
        store[0] = v

    backend = SoftSignalBackend(float, setter=setter)
    await backend.connect(timeout=1)
    await backend.put(7.0)
    assert store[0] == 7.0


async def test_soft_signal_backend_setter_returns_settled_value():
    def clamping_setter(v):
        return max(0.0, min(10.0, v))

    backend = SoftSignalBackend(float, setter=clamping_setter)
    await backend.connect(timeout=1)
    await backend.put(50.0)
    assert await backend.get_value() == 10.0


async def test_soft_signal_backend_setter_none_with_getter_refreshes():
    store = [0.0]

    def setter(v):
        store[0] = v

    backend = SoftSignalBackend(float, setter=setter, getter=lambda: store[0])
    await backend.connect(timeout=1)
    await backend.put(3.0)
    assert await backend.get_value() == 3.0


async def test_soft_signal_backend_setter_none_without_getter_stores_write_value():
    called_with = []

    def setter(v):
        called_with.append(v)

    backend = SoftSignalBackend(float, setter=setter)
    await backend.connect(timeout=1)
    await backend.put(6.0)
    assert called_with == [6.0]
    assert await backend.get_value() == 6.0


async def test_soft_signal_backend_poll_period_without_getter_raises():
    with pytest.raises(ValueError, match="poll_period requires a getter"):
        SoftSignalBackend(float, poll_period=0.1)


async def test_soft_signal_backend_poll_period_updates_via_callback():
    store = [0.0]
    backend = SoftSignalBackend(float, getter=lambda: store[0], poll_period=0.05)
    await backend.connect(timeout=1)

    updates: asyncio.Queue[Reading] = asyncio.Queue()
    backend.set_callback(updates.put_nowait)

    # Consume the initial callback fired by set_callback
    await updates.get()

    store[0] = 5.0
    reading = await asyncio.wait_for(updates.get(), timeout=1.0)
    assert reading["value"] == 5.0

    backend.set_callback(None)


async def test_soft_signal_backend_poll_task_starts_and_stops():
    backend = SoftSignalBackend(float, getter=lambda: 0.0, poll_period=0.05)
    await backend.connect(timeout=1)

    updates: asyncio.Queue[Reading] = asyncio.Queue()
    assert backend._poll_task is None

    backend.set_callback(updates.put_nowait)
    assert backend._poll_task is not None
    assert not backend._poll_task.cancelled()

    backend.set_callback(None)
    assert backend._poll_task is None


async def test_soft_signal_backend_no_poll_without_poll_period():
    # A getter without poll_period should not start a background task.
    backend = SoftSignalBackend(float, getter=lambda: 0.0)
    await backend.connect(timeout=1)

    updates: asyncio.Queue[Reading] = asyncio.Queue()
    backend.set_callback(updates.put_nowait)
    assert backend._poll_task is None
    backend.set_callback(None)
