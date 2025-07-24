from __future__ import annotations

import time
import typing
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Generic, get_args, get_origin

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey

from ._signal_backend import (
    Array1D,
    EnumT,
    Primitive,
    PrimitiveT,
    SignalBackend,
    SignalDatatype,
    SignalDatatypeT,
    TableT,
    make_datakey,
    make_metadata,
)
from ._table import Table
from ._utils import Callback, get_dtype, get_enum_cls


class SoftConverter(Generic[SignalDatatypeT]):
    # This is Any -> SignalDatatypeT because we support coercing
    # value types to SignalDatatype to allow people to do things like
    # SignalRW[Enum].set("enum value")
    @abstractmethod
    def write_value(self, value: Any) -> SignalDatatypeT: ...


@dataclass
class PrimitiveSoftConverter(SoftConverter[PrimitiveT]):
    datatype: type[PrimitiveT]

    def write_value(self, value: Any) -> PrimitiveT:
        return self.datatype(value) if value else self.datatype()


class SequenceStrSoftConverter(SoftConverter[Sequence[str]]):
    def write_value(self, value: Any) -> Sequence[str]:
        return [str(v) for v in value] if value else []


@dataclass
class SequenceEnumSoftConverter(SoftConverter[Sequence[EnumT]]):
    datatype: type[EnumT]

    def write_value(self, value: Any) -> Sequence[EnumT]:
        return [self.datatype(v) for v in value] if value else []


@dataclass
class NDArraySoftConverter(SoftConverter[Array1D]):
    datatype: np.dtype | None = None

    def write_value(self, value: Any) -> Array1D:
        return np.array(() if value is None else value, dtype=self.datatype)


@dataclass
class EnumSoftConverter(SoftConverter[EnumT]):
    datatype: type[EnumT]

    def write_value(self, value: Any) -> EnumT:
        return (
            self.datatype(value)
            if value
            else list(self.datatype.__members__.values())[0]
        )


@dataclass
class TableSoftConverter(SoftConverter[TableT]):
    datatype: type[TableT]

    def write_value(self, value: Any) -> TableT:
        if isinstance(value, dict):
            return self.datatype(**value)
        elif isinstance(value, self.datatype):
            return value
        elif value is None:
            return self.datatype()
        else:
            raise TypeError(f"Cannot convert {value} to {self.datatype}")


@lru_cache
def make_converter(datatype: type[SignalDatatype]) -> SoftConverter:
    enum_cls = get_enum_cls(datatype)
    if datatype in (Sequence[str], typing.Sequence[str]):
        return SequenceStrSoftConverter()
    elif get_origin(datatype) in (Sequence, typing.Sequence) and enum_cls:
        return SequenceEnumSoftConverter(enum_cls)
    elif datatype is np.ndarray:
        return NDArraySoftConverter()
    elif get_origin(datatype) == np.ndarray:
        if datatype not in get_args(SignalDatatype):
            raise TypeError(f"Expected Array1D[dtype], got {datatype}")
        return NDArraySoftConverter(get_dtype(datatype))
    elif enum_cls:
        return EnumSoftConverter(enum_cls)
    elif issubclass(datatype, Table):
        return TableSoftConverter(datatype)
    elif issubclass(datatype, Primitive):
        return PrimitiveSoftConverter(datatype)
    raise TypeError(f"Can't make converter for {datatype}")


class SoftSignalBackend(SignalBackend[SignalDatatypeT]):
    """An backend to a soft Signal, for test signals see [](#MockSignalBackend).

    :param datatype: The datatype of the signal, defaults to float if not given.
    :param initial_value:
        The initial value of the signal, defaults to the "empty", "zero" or
        "default" value of the datatype if not given.
    :param units: The units for numeric datatypes.
    :param precision:
        The number of digits after the decimal place to display for a float datatype.
    """

    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        initial_value: SignalDatatypeT | None = None,
        units: str | None = None,
        precision: int | None = None,
    ):
        # Create the right converter for the datatype
        self.converter = make_converter(datatype or float)
        # Add the extra static metadata to the dictionary
        self.metadata = make_metadata(datatype, units, precision)
        # Create and set the initial value
        self.initial_value = self.converter.write_value(initial_value)
        self.reading: Reading[SignalDatatypeT]
        self.callback: Callback[Reading[SignalDatatypeT]] | None = None
        self.set_value(self.initial_value)
        super().__init__(datatype)

    def set_value(self, value: SignalDatatypeT):
        """Set the current value, alarm and timestamp."""
        self.reading = Reading(
            value=self.converter.write_value(value),
            timestamp=time.time(),
            alarm_severity=0,
        )
        if self.callback:
            self.callback(self.reading)

    def source(self, name: str, read: bool) -> str:
        return f"soft://{name}"

    async def connect(self, timeout: float):
        pass

    async def put(self, value: SignalDatatypeT | None, wait: bool) -> None:
        write_value = self.initial_value if value is None else value
        self.set_value(write_value)

    async def get_datakey(self, source: str) -> DataKey:
        return make_datakey(
            self.datatype or float, self.reading["value"], source, self.metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        return self.reading

    async def get_value(self) -> SignalDatatypeT:
        return self.reading["value"]

    async def get_setpoint(self) -> SignalDatatypeT:
        # For a soft signal, the setpoint and readback values are the same.
        return self.reading["value"]

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback and self.callback:
            raise RuntimeError("Cannot set a callback when one is already set")
        if callback:
            callback(self.reading)
        self.callback = callback
