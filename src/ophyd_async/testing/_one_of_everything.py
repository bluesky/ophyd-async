from collections.abc import Sequence
from typing import Any

import numpy as np

from ophyd_async.core import (
    Array1D,
    Device,
    DTypeScalar_co,
    SignalRW,
    StandardReadable,
    StrictEnum,
    Table,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.core._device import DeviceVector


class ExampleEnum(StrictEnum):
    """Example of a strict Enum datatype."""

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


class OneOfEverythingDevice(StandardReadable):
    """A device with one of every datatype allowed on signals."""

    # make a detector to test assert_configuration
    def __init__(self, name=""):
        # add all signals to configuration
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.int = soft_signal_rw(int, 1)
            self.float = soft_signal_rw(float, 1.234)
            self.str = soft_signal_rw(str, "test_string")
            self.bool = soft_signal_rw(bool, True)
            self.enum = soft_signal_rw(ExampleEnum, ExampleEnum.B)
            self.int8a = int_array_signal(np.int8)
            self.uint8a = int_array_signal(np.uint8)
            self.int16a = int_array_signal(np.int16)
            self.uint16a = int_array_signal(np.uint16)
            self.int32a = int_array_signal(np.int32)
            self.uint32a = int_array_signal(np.uint32)
            self.int64a = int_array_signal(np.int64)
            self.uint64a = int_array_signal(np.uint64)
            self.float32a = float_array_signal(np.float32)
            self.float64a = float_array_signal(np.float64)
            self.stra = soft_signal_rw(
                Sequence[str],
                ["one", "two", "three"],
            )
            self.enuma = soft_signal_rw(
                Sequence[ExampleEnum],
                [ExampleEnum.A, ExampleEnum.C],
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
            )
            self.ndarray = soft_signal_rw(np.ndarray, np.array(([1, 2, 3], [4, 5, 6])))
        super().__init__(name)


async def _get_signal_values(child: Device) -> dict[SignalRW, Any]:
    if isinstance(child, SignalRW):
        return {child: await child.get_value()}
    ret = {}
    for _, c in child.children():
        ret.update(await _get_signal_values(c))
    return ret


class ParentOfEverythingDevice(Device):
    """Device containing subdevices with one of every datatype allowed on signals."""

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
