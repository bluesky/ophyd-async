from __future__ import annotations

import inspect
import time
from collections import abc
from enum import Enum
from typing import (
    Dict,
    Generic,
    Optional,
    Tuple,
    Type,
    TypedDict,
    Union,
    cast,
    get_origin,
)

import numpy as np
from bluesky.protocols import DataKey, Dtype, Reading

from .signal_backend import RuntimeSubsetEnum, SignalBackend
from .utils import DEFAULT_TIMEOUT, ReadingValueCallback, T, get_dtype

primitive_dtypes: Dict[type, Dtype] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class SignalMetadata(TypedDict):
    units: str | None = None
    precision: int | None = None


class SoftConverter(Generic[T]):
    def value(self, value: T) -> T:
        return value

    def write_value(self, value: T) -> T:
        return value

    def reading(self, value: T, timestamp: float, severity: int) -> Reading:
        return Reading(
            value=value,
            timestamp=timestamp,
            alarm_severity=-1 if severity > 2 else severity,
        )

    def get_datakey(self, source: str, value, **metadata) -> DataKey:
        dk = {"source": source, "shape": [], **metadata}
        dtype = type(value)
        if np.issubdtype(dtype, np.integer):
            dtype = int
        elif np.issubdtype(dtype, np.floating):
            dtype = float
        assert (
            dtype in primitive_dtypes
        ), f"invalid converter for value of type {type(value)}"
        dk["dtype"] = primitive_dtypes[dtype]
        try:
            dk["dtype_numpy"] = np.dtype(dtype).descr[0][1]
        except TypeError:
            dk["dtype_numpy"] = ""
        return dk

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        return datatype()


class SoftArrayConverter(SoftConverter):
    def get_datakey(self, source: str, value, **metadata) -> DataKey:
        dtype_numpy = ""
        if isinstance(value, list):
            if len(value) > 0:
                dtype_numpy = np.dtype(type(value[0])).descr[0][1]
        else:
            dtype_numpy = np.dtype(value.dtype).descr[0][1]

        return {
            "source": source,
            "dtype": "array",
            "dtype_numpy": dtype_numpy,
            "shape": [len(value)],
            **metadata,
        }

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        if get_origin(datatype) == abc.Sequence:
            return cast(T, [])

        return cast(T, datatype(shape=0))  # type: ignore


class SoftEnumConverter(SoftConverter):
    choices: Tuple[str, ...]

    def __init__(self, datatype: Union[RuntimeSubsetEnum, Enum]):
        if issubclass(datatype, Enum):
            self.choices = tuple(v.value for v in datatype)
        else:
            self.choices = datatype.choices

    def write_value(self, value: Union[Enum, str]) -> str:
        return value

    def get_datakey(self, source: str, value, **metadata) -> DataKey:
        return {
            "source": source,
            "dtype": "string",
            "dtype_numpy": "|S40",
            "shape": [],
            "choices": self.choices,
            **metadata,
        }

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        if issubclass(datatype, Enum):
            return cast(T, list(datatype.__members__.values())[0])  # type: ignore
        return cast(T, self.choices[0])


def make_converter(datatype):
    is_array = get_dtype(datatype) is not None
    is_sequence = get_origin(datatype) == abc.Sequence
    is_enum = inspect.isclass(datatype) and (
        issubclass(datatype, Enum) or issubclass(datatype, RuntimeSubsetEnum)
    )

    if is_array or is_sequence:
        return SoftArrayConverter()
    if is_enum:
        return SoftEnumConverter(datatype)

    return SoftConverter()


class SoftSignalBackend(SignalBackend[T]):
    """An backend to a soft Signal, for test signals see ``MockSignalBackend``."""

    _value: T
    _initial_value: Optional[T]
    _timestamp: float
    _severity: int

    def __init__(
        self,
        datatype: Optional[Type[T]],
        initial_value: Optional[T] = None,
        metadata: SignalMetadata = None,
    ) -> None:
        self.datatype = datatype
        self._initial_value = initial_value
        self._metadata = metadata or {}
        self.converter: SoftConverter = make_converter(datatype)
        if self._initial_value is None:
            self._initial_value = self.converter.make_initial_value(self.datatype)
        else:
            self._initial_value = self.converter.write_value(self._initial_value)

        self.callback: Optional[ReadingValueCallback[T]] = None
        self._severity = 0
        self.set_value(self._initial_value)

    def source(self, name: str) -> str:
        return f"soft://{name}"

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Connection isn't required for soft signals."""
        pass

    async def put(self, value: Optional[T], wait=True, timeout=None):
        write_value = (
            self.converter.write_value(value)
            if value is not None
            else self._initial_value
        )

        self.set_value(write_value)

    def set_value(self, value: T):
        """Method to bypass asynchronous logic."""
        self._value = value
        self._timestamp = time.monotonic()
        reading: Reading = self.converter.reading(
            self._value, self._timestamp, self._severity
        )

        if self.callback:
            self.callback(reading, self._value)

    async def get_datakey(self, source: str) -> DataKey:
        return self.converter.get_datakey(source, self._value, **self._metadata)

    async def get_reading(self) -> Reading:
        return self.converter.reading(self._value, self._timestamp, self._severity)

    async def get_value(self) -> T:
        return self.converter.value(self._value)

    async def get_setpoint(self) -> T:
        """For a soft signal, the setpoint and readback values are the same."""
        return await self.get_value()

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        if callback:
            assert not self.callback, "Cannot set a callback when one is already set"
            reading: Reading = self.converter.reading(
                self._value, self._timestamp, self._severity
            )
            callback(reading, self._value)
        self.callback = callback
