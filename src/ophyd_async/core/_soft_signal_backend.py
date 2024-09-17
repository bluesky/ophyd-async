from __future__ import annotations

import inspect
import time
from collections import abc
from enum import Enum
from typing import Generic, cast, get_origin

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey
from event_model.documents.event_descriptor import Dtype
from pydantic import BaseModel
from typing_extensions import TypedDict

from ._signal_backend import (
    RuntimeSubsetEnum,
    SignalBackend,
)
from ._utils import (
    DEFAULT_TIMEOUT,
    ReadingValueCallback,
    T,
    get_dtype,
    is_pydantic_model,
)

primitive_dtypes: dict[type, Dtype] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class SignalMetadata(TypedDict):
    units: str | None
    precision: int | None


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
        dk: DataKey = {"source": source, "shape": [], **metadata}  # type: ignore
        dtype = type(value)
        if np.issubdtype(dtype, np.integer):
            dtype = int
        elif np.issubdtype(dtype, np.floating):
            dtype = float
        assert (
            dtype in primitive_dtypes
        ), f"invalid converter for value of type {type(value)}"
        dk["dtype"] = primitive_dtypes[dtype]
        # type ignore until https://github.com/bluesky/event-model/issues/308
        try:
            dk["dtype_numpy"] = np.dtype(dtype).descr[0][1]  # type: ignore
        except TypeError:
            dk["dtype_numpy"] = ""  # type: ignore
        return dk

    def make_initial_value(self, datatype: type[T] | None) -> T:
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
            "dtype_numpy": dtype_numpy,  # type: ignore
            "shape": [len(value)],
            **metadata,
        }

    def make_initial_value(self, datatype: type[T] | None) -> T:
        if datatype is None:
            return cast(T, None)

        if get_origin(datatype) == abc.Sequence:
            return cast(T, [])

        return cast(T, datatype(shape=0))  # type: ignore


class SoftEnumConverter(SoftConverter):
    choices: tuple[str, ...]

    def __init__(self, datatype: RuntimeSubsetEnum | type[Enum]):
        if issubclass(datatype, Enum):  # type: ignore
            self.choices = tuple(v.value for v in datatype)
        else:
            self.choices = datatype.choices

    def write_value(self, value: Enum | str) -> str:
        return value  # type: ignore

    def get_datakey(self, source: str, value, **metadata) -> DataKey:
        return {
            "source": source,
            "dtype": "string",
            # type ignore until https://github.com/bluesky/event-model/issues/308
            "dtype_numpy": "|S40",  # type: ignore
            "shape": [],
            "choices": self.choices,
            **metadata,
        }

    def make_initial_value(self, datatype: type[T] | None) -> T:
        if datatype is None:
            return cast(T, None)

        if issubclass(datatype, Enum):
            return cast(T, list(datatype.__members__.values())[0])  # type: ignore
        return cast(T, self.choices[0])


class SoftPydanticModelConverter(SoftConverter):
    def __init__(self, datatype: type[BaseModel]):
        self.datatype = datatype

    def write_value(self, value):
        if isinstance(value, dict):
            return self.datatype(**value)
        return value


def make_converter(datatype):
    is_array = get_dtype(datatype) is not None
    is_sequence = get_origin(datatype) == abc.Sequence
    is_enum = inspect.isclass(datatype) and (
        issubclass(datatype, Enum) or issubclass(datatype, RuntimeSubsetEnum)
    )

    if is_array or is_sequence:
        return SoftArrayConverter()
    if is_enum:
        return SoftEnumConverter(datatype)  # type: ignore
    if is_pydantic_model(datatype):
        return SoftPydanticModelConverter(datatype)  # type: ignore

    return SoftConverter()


class SoftSignalBackend(SignalBackend[T]):
    """An backend to a soft Signal, for test signals see ``MockSignalBackend``."""

    _value: T
    _initial_value: T | None
    _timestamp: float
    _severity: int

    @classmethod
    def datatype_allowed(cls, dtype: type) -> bool:
        return True  # Any value allowed in a soft signal

    def __init__(
        self,
        datatype: type[T] | None,
        initial_value: T | None = None,
        metadata: SignalMetadata = None,  # type: ignore
    ) -> None:
        self.datatype = datatype
        self._initial_value = initial_value
        self._metadata = metadata or {}
        self.converter: SoftConverter = make_converter(datatype)
        if self._initial_value is None:
            self._initial_value = self.converter.make_initial_value(self.datatype)
        else:
            self._initial_value = self.converter.write_value(self._initial_value)  # type: ignore

        self.callback: ReadingValueCallback[T] | None = None
        self._severity = 0
        self.set_value(self._initial_value)  # type: ignore

    def source(self, name: str) -> str:
        return f"soft://{name}"

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Connection isn't required for soft signals."""
        pass

    async def put(self, value: T | None, wait=True, timeout=None):
        write_value = (
            self.converter.write_value(value)
            if value is not None
            else self._initial_value
        )

        self.set_value(write_value)  # type: ignore

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

    def set_callback(self, callback: ReadingValueCallback[T] | None) -> None:
        if callback:
            assert not self.callback, "Cannot set a callback when one is already set"
            reading: Reading = self.converter.reading(
                self._value, self._timestamp, self._severity
            )
            callback(reading, self._value)
        self.callback = callback
