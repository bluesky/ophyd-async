import asyncio
import time
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import Signal, SignalBackend, SignalMetadata, SoftSignalBackend, T


class MyEnum(str, Enum):
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
    return {"dtype": "string", "shape": [], "choices": ("Aaa", "Bbb", "Ccc")}


def waveform_d(value):
    return {"dtype": "array", "shape": [len(value)]}


class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.updates: asyncio.Queue[tuple[Reading, Any]] = asyncio.Queue()
        backend.set_callback(self.add_reading_value)

    def add_reading_value(self, reading: Reading, value):
        self.updates.put_nowait((reading, value))

    async def assert_updates(self, expected_value):
        expected_reading = {
            "value": expected_value,
            "timestamp": pytest.approx(time.monotonic(), rel=0.1),
            "alarm_severity": 0,
        }
        reading, value = await self.updates.get()

        backend_value = await self.backend.get_value()
        backend_reading = await self.backend.get_reading()

        assert value == expected_value == backend_value
        assert reading == expected_reading == backend_reading

    def close(self):
        self.backend.set_callback(None)


@pytest.mark.parametrize(
    "datatype, initial_value, put_value, descriptor, dtype_numpy",
    [
        (int, 0, 43, integer_d, "<i8"),
        (float, 0.0, 43.5, number_d, "<f8"),
        (str, "", "goodbye", string_d, "<U0"),
        (MyEnum, MyEnum.a, MyEnum.c, enum_d, "|S40"),
        (npt.NDArray[np.int8], [], [-8, 3, 44], waveform_d, "<f8"),
        (npt.NDArray[np.uint8], [], [218], waveform_d, "<f8"),
        (npt.NDArray[np.int16], [], [-855], waveform_d, "<f8"),
        (npt.NDArray[np.uint16], [], [5666], waveform_d, "<f8"),
        (npt.NDArray[np.int32], [], [-2], waveform_d, "<f8"),
        (npt.NDArray[np.uint32], [], [1022233], waveform_d, "<f8"),
        (npt.NDArray[np.int64], [], [-3], waveform_d, "<f8"),
        (npt.NDArray[np.uint64], [], [995444], waveform_d, "<f8"),
        (npt.NDArray[np.float32], [], [1.0], waveform_d, "<f8"),
        (npt.NDArray[np.float64], [], [0.2], waveform_d, "<f8"),
        (Sequence[str], [], ["nine", "ten"], waveform_d, ""),
        # Can't do long strings until https://github.com/epics-base/pva2pva/issues/17
        # (str, "longstr", ls1, ls2, string_d),
        # (str, "longstr2.VAL$", ls1, ls2, string_d),
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

    await backend.connect()
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
        await backend.put(put_value)
        await q.assert_updates(pytest.approx(put_value))
    finally:
        q.close()


async def test_soft_signal_backend_enum_value_equivalence():
    soft_signal = SoftSignalBackend(MyEnum)
    await soft_signal.connect()
    assert (await soft_signal.get_value()) is MyEnum.a
    await soft_signal.put(MyEnum.b)
    assert (await soft_signal.get_value()) is MyEnum.b


async def test_soft_signal_backend_with_numpy_typing():
    soft_backend = SoftSignalBackend(npt.NDArray[np.float64])
    await soft_backend.connect()

    array = await soft_backend.get_value()
    assert array.shape == (0,)


async def test_soft_signal_descriptor_fails_for_invalid_class():
    class myClass:
        def __init__(self) -> None:
            pass

    soft_signal = Signal(SoftSignalBackend(myClass))
    await soft_signal.connect()

    with pytest.raises(AssertionError):
        await soft_signal._backend.get_datakey("")


async def test_soft_signal_descriptor_with_metadata():
    soft_signal = Signal(
        SoftSignalBackend(int, 0, metadata=SignalMetadata(units="mm", precision=0))
    )
    await soft_signal.connect()
    datakey = await soft_signal._backend.get_datakey("")
    assert datakey["units"] == "mm"
    assert datakey["precision"] == 0

    soft_signal = Signal(SoftSignalBackend(int, metadata=SignalMetadata(units="")))
    await soft_signal.connect()
    datakey = await soft_signal._backend.get_datakey("")
    assert datakey["units"] == ""
    assert not hasattr(datakey, "precision")


async def test_soft_signal_descriptor_with_no_metadata_not_passed():
    soft_signal = Signal(SoftSignalBackend(int))
    await soft_signal.connect()
    datakey = await soft_signal._backend.get_datakey("")
    assert not hasattr(datakey, "units")
    assert not hasattr(datakey, "precision")

    soft_signal = Signal(SoftSignalBackend(int, metadata=None))
    await soft_signal.connect()
    datakey = await soft_signal._backend.get_datakey("")
    assert not hasattr(datakey, "units")
    assert not hasattr(datakey, "precision")

    soft_signal = Signal(SoftSignalBackend(int, metadata={}))
    await soft_signal.connect()
    datakey = await soft_signal._backend.get_datakey("")
    assert not hasattr(datakey, "units")
    assert not hasattr(datakey, "precision")
