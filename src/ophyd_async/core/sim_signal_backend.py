from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections import abc
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Generic, Optional, Type, Union, cast, get_origin

from bluesky.protocols import Descriptor, Dtype, Reading

from .signal_backend import SignalBackend
from .utils import DEFAULT_TIMEOUT, ReadingValueCallback, T, get_dtype

primitive_dtypes: Dict[type, Dtype] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class SimConverter(Generic[T]):
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

    def descriptor(self, source: str, value) -> Descriptor:
        assert (
            type(value) in primitive_dtypes
        ), f"invalid converter for value of type {type(value)}"
        dtype = primitive_dtypes[type(value)]
        return dict(source=source, dtype=dtype, shape=[])

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        return datatype()


class SimArrayConverter(SimConverter):
    def descriptor(self, source: str, value) -> Descriptor:
        return dict(source=source, dtype="array", shape=[len(value)])

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        if get_origin(datatype) == abc.Sequence:
            return cast(T, [])

        return cast(T, datatype(shape=0))  # type: ignore


@dataclass
class SimEnumConverter(SimConverter):
    enum_class: Type[Enum]

    def write_value(self, value: Union[Enum, str]) -> Enum:
        if isinstance(value, Enum):
            return value
        else:
            return self.enum_class(value)

    def descriptor(self, source: str, value) -> Descriptor:
        choices = [e.value for e in self.enum_class]
        return dict(
            source=source, dtype="string", shape=[], choices=choices
        )  # type: ignore

    def make_initial_value(self, datatype: Optional[Type[T]]) -> T:
        if datatype is None:
            return cast(T, None)

        return cast(T, list(datatype.__members__.values())[0])  # type: ignore


class DisconnectedSimConverter(SimConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


def make_converter(datatype):
    is_array = get_dtype(datatype) is not None
    is_sequence = get_origin(datatype) == abc.Sequence
    is_enum = issubclass(datatype, Enum) if inspect.isclass(datatype) else False

    if is_array or is_sequence:
        return SimArrayConverter()
    if is_enum:
        return SimEnumConverter(datatype)

    return SimConverter()


class SimSignalBackend(SignalBackend[T]):
    """An simulated backend to a Signal, created with ``Signal.connect(sim=True)``"""

    _value: T
    _initial_value: Optional[T]
    _timestamp: float
    _severity: int

    def __init__(
        self,
        datatype: Optional[Type[T]],
        source: str,
        initial_value: Optional[T] = None,
    ) -> None:
        pv = re.split(r"://", source)[-1]
        self.source = f"sim://{pv}"
        self.datatype = datatype
        self.pv = source
        self.converter: SimConverter = DisconnectedSimConverter()
        self._initial_value = initial_value
        self.put_proceeds = asyncio.Event()
        self.put_proceeds.set()
        self.callback: Optional[ReadingValueCallback[T]] = None

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.converter = make_converter(self.datatype)
        if self._initial_value is None:
            self._initial_value = self.converter.make_initial_value(self.datatype)
        else:
            # convert potentially unconverted initial value passed to init method
            self._initial_value = self.converter.write_value(self._initial_value)
        self._severity = 0

        await self.put(None)

    async def put(self, value: Optional[T], wait=True, timeout=None):
        write_value = (
            self.converter.write_value(value)
            if value is not None
            else self._initial_value
        )
        self._set_value(write_value)

        if wait:
            await asyncio.wait_for(self.put_proceeds.wait(), timeout)

    def _set_value(self, value: T):
        """Method to bypass asynchronous logic, designed to only be used in tests."""
        self._value = value
        self._timestamp = time.monotonic()
        reading: Reading = self.converter.reading(
            self._value, self._timestamp, self._severity
        )

        if self.callback:
            self.callback(reading, self._value)

    async def get_descriptor(self) -> Descriptor:
        return self.converter.descriptor(self.source, self._value)

    async def get_reading(self) -> Reading:
        return self.converter.reading(self._value, self._timestamp, self._severity)

    async def get_value(self) -> T:
        return self.converter.value(self._value)

    async def get_setpoint(self) -> T:
        """For a simulated backend, the setpoint and readback values are the same."""
        return await self.get_value()

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        if callback:
            assert not self.callback, "Cannot set a callback when one is already set"
            reading: Reading = self.converter.reading(
                self._value, self._timestamp, self._severity
            )
            callback(reading, self._value)
        self.callback = callback
