import asyncio
import time
from enum import Enum
from typing import Any, Callable, Sequence, Tuple, Type

import numpy as np
import numpy.typing as npt
import pytest
from bluesky.protocols import Reading

from ophyd_async.core.backends import SignalBackend, SimSignalBackend
from ophyd_async.core.signal import Signal
from ophyd_async.core.utils import T


class MyEnum(str, Enum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


def integer_d(value):
    return dict(dtype="integer", shape=[])


def number_d(value):
    return dict(dtype="number", shape=[])


def string_d(value):
    return dict(dtype="string", shape=[])


def enum_d(value):
    return dict(dtype="string", shape=[], choices=["Aaa", "Bbb", "Ccc"])


def waveform_d(value):
    return dict(dtype="array", shape=[len(value)])


class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.updates: asyncio.Queue[Tuple[Reading, Any]] = asyncio.Queue()
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
    "datatype, initial_value, put_value, descriptor",
    [
        (int, 0, 43, integer_d),
        (float, 0.0, 43.5, number_d),
        (str, "", "goodbye", string_d),
        (MyEnum, MyEnum.a, MyEnum.c, enum_d),
        (npt.NDArray[np.int8], [], [-8, 3, 44], waveform_d),
        (npt.NDArray[np.uint8], [], [218], waveform_d),
        (npt.NDArray[np.int16], [], [-855], waveform_d),
        (npt.NDArray[np.uint16], [], [5666], waveform_d),
        (npt.NDArray[np.int32], [], [-2], waveform_d),
        (npt.NDArray[np.uint32], [], [1022233], waveform_d),
        (npt.NDArray[np.int64], [], [-3], waveform_d),
        (npt.NDArray[np.uint64], [], [995444], waveform_d),
        (npt.NDArray[np.float32], [], [1.0], waveform_d),
        (npt.NDArray[np.float64], [], [0.2], waveform_d),
        (Sequence[str], [], ["nine", "ten"], waveform_d),
        # Can't do long strings until https://github.com/epics-base/pva2pva/issues/17
        # (str, "longstr", ls1, ls2, string_d),
        # (str, "longstr2.VAL$", ls1, ls2, string_d),
    ],
)
async def test_backend_get_put_monitor(
    datatype: Type[T],
    initial_value: T,
    put_value: T,
    descriptor: Callable[[Any], dict],
):
    backend = SimSignalBackend(datatype, "")

    await backend.connect()
    q = MonitorQueue(backend)
    try:
        # Check descriptor
        assert (
            dict(source="sim://", **descriptor(initial_value))
            == await backend.get_descriptor()
        )
        # Check initial value
        await q.assert_updates(
            pytest.approx(initial_value) if initial_value != "" else initial_value
        )
        # Put to new value and check that
        await backend.put(put_value)
        await q.assert_updates(pytest.approx(put_value))
    finally:
        q.close()


async def test_sim_backend_if_disconnected():
    sim_backend = SimSignalBackend(npt.NDArray[np.float64], "SOME-IOC:PV")
    with pytest.raises(NotImplementedError):
        await sim_backend.get_value()


async def test_sim_backend_with_numpy_typing():
    sim_backend = SimSignalBackend(npt.NDArray[np.float64], "SOME-IOC:PV")
    await sim_backend.connect()

    array = await sim_backend.get_value()
    assert array.shape == (0,)


async def test_sim_backend_descriptor_fails_for_invalid_class():
    class myClass:
        def __init__(self) -> None:
            pass

    sim_signal = Signal(SimSignalBackend(myClass, "test"))
    await sim_signal.connect(sim=True)

    with pytest.raises(AssertionError):
        await sim_signal._backend.get_descriptor()
