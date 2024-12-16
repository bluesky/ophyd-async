from collections.abc import Sequence
from typing import Any

import numpy as np

from ophyd_async.core import (
    Array1D,
    DetectorController,
    DetectorWriter,
    Device,
    DTypeScalar_co,
    SignalR,
    SignalRW,
    StandardDetector,
    StrictEnum,
    Table,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core._device import DeviceVector


class ExampleEnum(StrictEnum):
    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


class ExampleTable(Table):
    bool: Array1D[np.bool_]
    int: Array1D[np.int32]
    float: Array1D[np.float64]
    str: Sequence[str]
    enum: Sequence[ExampleEnum]


def int_array_signal(
    dtype: type[DTypeScalar_co], name: str = ""
) -> SignalRW[Array1D[DTypeScalar_co]]:
    iinfo = np.iinfo(dtype)  # type: ignore
    value = np.array([iinfo.min, iinfo.max, 0, 1, 2, 3, 4], dtype=dtype)
    return soft_signal_rw(Array1D[dtype], value, name)


def float_array_signal(
    dtype: type[DTypeScalar_co], name: str = ""
) -> SignalRW[Array1D[DTypeScalar_co]]:
    finfo = np.finfo(dtype)  # type: ignore
    value = np.array(
        [
            finfo.min,
            finfo.max,
            finfo.smallest_normal,
            finfo.smallest_subnormal,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=dtype,
    )
    return soft_signal_rw(Array1D[dtype], value, name)


class DummyController(DetectorController):
    def get_deadtime(self, exposure: float | None) -> float: ...

    async def prepare(self, trigger_info): ...

    async def arm(self) -> None: ...

    async def wait_for_idle(self): ...

    async def disarm(self): ...


class DummyWriter(DetectorWriter):
    async def open(self, multiplier: int = 1):
        return {}

    def observe_indices_written(self, timeout: float = 10.0):
        raise NotImplementedError()

    async def get_indices_written(self) -> int:
        return 0

    def collect_stream_docs(self, indices_written: int):
        raise NotImplementedError()

    async def close(self) -> None: ...


class OneOfEverythingDevice(StandardDetector):
    # make a detector to test assert_configuration
    def __init__(self, name=""):
        self.int = soft_signal_rw(int, 1, name="int")
        self.float = soft_signal_rw(float, 1.234, name="float")
        self.str = soft_signal_rw(str, "test_string", name="str")
        self.bool = soft_signal_rw(bool, True, name="bool")
        self.enum = soft_signal_rw(ExampleEnum, ExampleEnum.B, name="enum")
        self.int8a = int_array_signal(np.int8, name="int8a")
        self.uint8a = int_array_signal(np.uint8, name="uint8a")
        self.int16a = int_array_signal(np.int16, name="int16a")
        self.uint16a = int_array_signal(np.uint16, name="uint16a")
        self.int32a = int_array_signal(np.int32, name="int32a")
        self.uint32a = int_array_signal(np.uint32, name="uint32a")
        self.int64a = int_array_signal(np.int64, name="int64a")
        self.uint64a = int_array_signal(np.uint64, name="uint64a")
        self.float32a = float_array_signal(np.float32, name="float32a")
        self.float64a = float_array_signal(np.float64, name="float64a")
        self.stra = soft_signal_rw(Sequence[str], ["one", "two", "three"], name="stra")
        self.enuma = soft_signal_rw(
            Sequence[ExampleEnum], [ExampleEnum.A, ExampleEnum.C], name="enuma"
        )
        self.table = soft_signal_rw(
            ExampleTable,
            ExampleTable(
                bool=np.array([False, False, True, True], np.bool_),
                int=np.array([1, 8, -9, 32], np.int32),
                float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
                str=["Hello", "World", "Foo", "Bar"],
                enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
            ),
            name="table",
        )
        self.ndarray = soft_signal_rw(
            np.ndarray, np.array(([1, 2, 3], [4, 5, 6])), name="ndarray"
        )
        signals = [sig for sig in self.__dict__.values() if isinstance(sig, SignalR)]
        # add all signals to config
        super().__init__(
            controller=DummyController(),
            writer=DummyWriter(),
            config_sigs=signals,
            name=name,
        )


async def _get_signal_values(child: Device) -> dict[SignalRW, Any]:
    if isinstance(child, SignalRW):
        return {child: await child.get_value()}
    ret = {}
    for _, c in child.children():
        ret.update(await _get_signal_values(c))
    return ret


class ParentOfEverythingDevice(Device):
    def __init__(self, name=""):
        self.child = OneOfEverythingDevice()
        self.vector = DeviceVector(
            {1: OneOfEverythingDevice(), 3: OneOfEverythingDevice()}
        )
        self.sig_rw = soft_signal_rw(str, "Top level SignalRW")
        self.sig_r, _ = soft_signal_r_and_setter(str, "Top level SignalR")
        self._sig_rw = soft_signal_rw(str, "Top level private SignalRW")
        super().__init__(name=name)

    async def get_signal_values(self):
        return await _get_signal_values(self)
