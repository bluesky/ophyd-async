from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ophyd_async.core import (
    Array1D,
    Device,
    DTypeScalar_co,
    SignalDatatype,
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
    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


class ExampleTable(Table):
    bool: Array1D[np.bool_]
    int: Array1D[np.int32]
    float: Array1D[np.float64]
    str: Sequence[str]
    enum: Sequence[ExampleEnum]


def int_array_value(dtype: type[DTypeScalar_co]) -> Array1D[DTypeScalar_co]:
    iinfo = np.iinfo(dtype)  # type: ignore
    return np.array([iinfo.min, iinfo.max, 0, 1, 2, 3, 4], dtype=dtype)


def float_array_value(dtype: type[DTypeScalar_co]) -> Array1D[DTypeScalar_co]:
    finfo = np.finfo(dtype)  # type: ignore
    return np.array(
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


@dataclass
class EverythingSignal:
    name: str
    dtype: type[SignalDatatype]
    initial_value: Any = None


def get_every_signal_data():
    # list containing necessary info to construct a signal of each type for multiple
    # transports e.g. soft/epics/tango
    return [
        EverythingSignal("int", int, 1),
        EverythingSignal("float", float, 1.234),
        EverythingSignal("str", str, "test_string"),
        EverythingSignal("bool", bool, True),
        EverythingSignal("enum", ExampleEnum, ExampleEnum.B),
        EverythingSignal("int8a", Array1D[np.int8], int_array_value(np.int8)),
        EverythingSignal("uint8a", Array1D[np.uint8], int_array_value(np.uint8)),
        EverythingSignal("int16a", Array1D[np.int16], int_array_value(np.int16)),
        EverythingSignal("uint16a", Array1D[np.uint16], int_array_value(np.uint16)),
        EverythingSignal("int32a", Array1D[np.int32], int_array_value(np.int32)),
        EverythingSignal("uint32a", Array1D[np.uint32], int_array_value(np.uint32)),
        EverythingSignal("int64a", Array1D[np.int64], int_array_value(np.int64)),
        EverythingSignal("uint64a", Array1D[np.uint64], int_array_value(np.uint64)),
        EverythingSignal(
            "float32a", Array1D[np.float32], float_array_value(np.float32)
        ),
        EverythingSignal(
            "float64a", Array1D[np.float64], float_array_value(np.float64)
        ),
        EverythingSignal("stra", Sequence[str], ["one", "two", "three"]),
        EverythingSignal(
            "enuma", Sequence[ExampleEnum], [ExampleEnum.A, ExampleEnum.C]
        ),
        EverythingSignal(
            "table",
            ExampleTable,
            ExampleTable(
                bool=np.array([False, False, True, True], np.bool_),
                int=np.array([1, 8, -9, 32], np.int32),
                float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
                str=["Hello", "World", "Foo", "Bar"],
                enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
            ),
        ),
        EverythingSignal("ndarray", np.ndarray, np.array(([1, 2, 3], [4, 5, 6]))),
    ]


class OneOfEverythingDevice(StandardReadable):
    # make a detector to test assert_configuration
    def __init__(self, name=""):
        # add all signals to configuration
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            for data in get_every_signal_data():
                setattr(self, data.name, soft_signal_rw(data.dtype, data.initial_value))
        super().__init__(name)


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
