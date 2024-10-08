from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Generic, get_origin
from unittest.mock import AsyncMock

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey

from ._signal_backend import (
    Array1D,
    EnumT,
    Primitive,
    PrimitiveT,
    SignalBackend,
    SignalConnector,
    SignalDatatype,
    SignalDatatypeT,
    SignalMetadata,
    TableT,
    make_datakey,
)
from ._table import Table
from ._utils import Callback, get_dtype, get_enum_cls


class SoftConverter(Generic[SignalDatatypeT]):
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
    datatype: np.dtype

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


def make_converter(datatype: type[SignalDatatype]) -> SoftConverter:
    enum_cls = get_enum_cls(datatype)
    if datatype == Sequence[str]:
        return SequenceStrSoftConverter()
    elif get_origin(datatype) == Sequence and enum_cls:
        return SequenceEnumSoftConverter(enum_cls)
    elif get_origin(datatype) == np.ndarray:
        return NDArraySoftConverter(get_dtype(datatype))
    elif enum_cls:
        return EnumSoftConverter(enum_cls)
    elif issubclass(datatype, Table):
        return TableSoftConverter(datatype)
    elif issubclass(datatype, Primitive):
        return PrimitiveSoftConverter(datatype)
    raise TypeError(f"Can't make converter for {datatype}")


class SoftSignalBackend(SignalBackend[SignalDatatypeT]):
    """An backend to a soft Signal, for test signals see ``MockSignalBackend``."""

    _reading: Reading[SignalDatatypeT]
    _callback: Callback[Reading[SignalDatatypeT]] | None = None

    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None = None,
        initial_value: SignalDatatypeT | None = None,
        metadata: SignalMetadata | None = None,
    ):
        # If not specified then default to float
        self._datatype = datatype or float
        # Create the right converter for the datatype
        self._converter = make_converter(self._datatype)
        self._initial_value = self._converter.write_value(initial_value)
        self._metadata = metadata or SignalMetadata()
        if enum_cls := get_enum_cls(self._datatype):
            self._metadata["choices"] = [v.value for v in enum_cls]
        self.set_value(self._initial_value)

    def set_value(self, value: SignalDatatypeT):
        self._reading = Reading(
            value=value, timestamp=time.monotonic(), alarm_severity=0
        )
        if self._callback:
            self._callback(self._reading)

    async def put(self, value: SignalDatatypeT | None, wait=True, timeout=None) -> None:
        write_value = (
            self._converter.write_value(value)
            if value is not None
            else self._initial_value
        )
        self.set_value(write_value)

    async def get_datakey(self, source: str) -> DataKey:
        return make_datakey(
            self._datatype, self._reading["value"], source, self._metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        return self._reading

    async def get_value(self) -> SignalDatatypeT:
        return self._reading["value"]

    async def get_setpoint(self) -> SignalDatatypeT:
        # For a soft signal, the setpoint and readback values are the same.
        return self._reading["value"]

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback:
            assert not self._callback, "Cannot set a callback when one is already set"
            callback(self._reading)
        self._callback = callback


class MockSignalBackend(SoftSignalBackend[SignalDatatypeT]):
    @cached_property
    def put_mock(self) -> AsyncMock:
        return AsyncMock(name="put", spec=Callable)

    @cached_property
    def put_proceeds(self) -> asyncio.Event:
        put_proceeds = asyncio.Event()
        put_proceeds.set()
        return put_proceeds

    async def put(self, value: SignalDatatypeT | None, wait=True, timeout=None):
        await self.put_mock(value, wait=wait, timeout=timeout)
        await super().put(value, wait, timeout)

        if wait:
            await asyncio.wait_for(self.put_proceeds.wait(), timeout=timeout)


@dataclass
class SoftSignalConnector(SignalConnector[SignalDatatypeT]):
    datatype: type[SignalDatatypeT]
    initial_value: SignalDatatypeT | None = None
    units: str | None = None
    precision: int | None = None

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        # Add the extra static metadata to the dictionary
        metadata: SignalMetadata = {}
        if self.units is not None:
            metadata["units"] = self.units
        if self.precision is not None:
            metadata["precision"] = self.precision
        # Create the backend
        backend_cls = MockSignalBackend if mock else SoftSignalBackend
        self.backend = backend_cls(self.datatype, self.initial_value, metadata)

    def source(self, name: str) -> str:
        return f"soft://{name}"

    def set_value(self, value: SignalDatatypeT):
        assert isinstance(
            self.backend, SoftSignalBackend
        ), "Cannot set soft signal value until after connect"
        self.backend.set_value(value)
