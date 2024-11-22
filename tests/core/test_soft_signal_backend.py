import asyncio
import os
import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    Array1D,
    SignalBackend,
    SoftSignalBackend,
    StrictEnum,
    T,
    soft_signal_rw,
)


class MyEnum(StrictEnum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


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


class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.updates: asyncio.Queue[Reading] = asyncio.Queue()
        backend.set_callback(self.updates.put_nowait)

    async def assert_updates(self, expected_value):
        expected_reading = {
            "value": expected_value,
            "timestamp": pytest.approx(time.monotonic(), rel=0.1),
            "alarm_severity": 0,
        }
        reading = await self.updates.get()

        backend_value = await self.backend.get_value()
        backend_reading = await self.backend.get_reading()

        assert reading["value"] == expected_value == backend_value
        assert reading == expected_reading == backend_reading

    def close(self):
        self.backend.set_callback(None)


# Can be removed once numpy >=2 is pinned.
default_int_type = (
    "<i4" if os.name == "nt" and np.version.version.startswith("1.") else "<i8"
)


@pytest.mark.parametrize(
    "datatype, initial_value, put_value, descriptor, dtype_numpy",
    [
        (int, 0, 43, integer_d, default_int_type),
        (float, 0.0, 43.5, number_d, "<f8"),
        (str, "", "goodbye", string_d, "|S40"),
        (MyEnum, MyEnum.a, MyEnum.c, enum_d, "|S40"),
        (Array1D[np.int8], [], [-8, 3, 44], waveform_d, "|i1"),
        (Array1D[np.uint8], [], [218], waveform_d, "|u1"),
        (Array1D[np.int16], [], [-855], waveform_d, "<i2"),
        (Array1D[np.uint16], [], [5666], waveform_d, "<u2"),
        (Array1D[np.int32], [], [-2], waveform_d, "<i4"),
        (Array1D[np.uint32], [], [1022233], waveform_d, "<u4"),
        (Array1D[np.int64], [], [-3], waveform_d, "<i8"),
        (Array1D[np.uint64], [], [995444], waveform_d, "<u8"),
        (Array1D[np.float32], [], [1.0], waveform_d, "<f4"),
        (Array1D[np.float64], [], [0.2], waveform_d, "<f8"),
        (Sequence[str], [], ["nine", "ten"], waveform_d, "|S40"),
    ],
)
async def test_soft_signal_backend_get_put_monitor(
    datatype: type[T],
    initial_value: T,
    put_value: T,
    descriptor: Callable[[Any], dict],
    dtype_numpy: str,
):
    backend = SoftSignalBackend(datatype=datatype)

    await backend.connect(1)
    q = MonitorQueue(backend)
    try:
        # Check descriptor
        source = "soft://test"
        # Add expected dtype_numpy to descriptor
        assert dict(
            source=source, **descriptor(initial_value), dtype_numpy=dtype_numpy
        ) == await backend.get_datakey(source)
        # Check initial value
        await q.assert_updates(
            pytest.approx(initial_value) if initial_value != "" else initial_value
        )
        # Put to new value and check that
        await backend.put(put_value, True)
        await q.assert_updates(pytest.approx(put_value))
    finally:
        q.close()


async def test_soft_signal_backend_enum_value_equivalence():
    soft_backend = SoftSignalBackend(MyEnum)
    await soft_backend.connect(timeout=1)
    assert (await soft_backend.get_value()) is MyEnum.a
    await soft_backend.put(MyEnum.b, True)
    assert (await soft_backend.get_value()) is MyEnum.b


async def test_soft_signal_backend_with_numpy_typing():
    soft_backend = SoftSignalBackend(Array1D[np.float64])
    await soft_backend.connect(timeout=1)
    array = await soft_backend.get_value()
    assert array.shape == (0,)


async def test_soft_signal_descriptor_fails_for_invalid_class():
    class myClass:
        def __init__(self) -> None:
            pass

    with pytest.raises(TypeError):
        SoftSignalBackend(myClass)


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
