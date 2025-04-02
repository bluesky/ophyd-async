from __future__ import annotations

import asyncio
import atexit
import logging
import typing
from collections.abc import Mapping, Sequence
from math import isnan, nan
from typing import Any, Generic

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey, Limits, LimitsRange
from p4p import Value
from p4p.client.asyncio import Context, Subscription
from pydantic import BaseModel

from ophyd_async.core import (
    Array1D,
    Callback,
    NotConnected,
    SignalDatatype,
    SignalDatatypeT,
    SignalMetadata,
    StrictEnum,
    Table,
    get_enum_cls,
    get_unique,
    make_datakey,
    wait_for_connection,
)

from ._util import EpicsSignalBackend, format_datatype, get_supported_values

logger = logging.getLogger("ophyd_async")


def _limits_from_value(value: Any) -> Limits:
    def get_limits(
        substucture_name: str, low_name: str = "limitLow", high_name: str = "limitHigh"
    ) -> LimitsRange | None:
        substructure = getattr(value, substucture_name, None)
        low = getattr(substructure, low_name, nan)
        high = getattr(substructure, high_name, nan)
        if not (isnan(low) and isnan(high)) and not low == high == 0:
            return LimitsRange(
                low=None if isnan(low) else low,
                high=None if isnan(high) else high,
            )
        return None

    limits = Limits()
    if limits_range := get_limits("valueAlarm", "lowAlarmLimit", "highAlarmLimit"):
        limits["alarm"] = limits_range
    if limits_range := get_limits("control"):
        limits["control"] = limits_range
    if limits_range := get_limits("display"):
        limits["display"] = limits_range
    if limits_range := get_limits("valueAlarm", "lowWarningLimit", "highWarningLimit"):
        limits["warning"] = limits_range
    return limits


def _metadata_from_value(datatype: type[SignalDatatype], value: Any) -> SignalMetadata:
    metadata = SignalMetadata()
    value_data: Any = getattr(value, "value", None)
    specifier = _get_specifier(value)
    display_data: Any = getattr(value, "display", None)
    if (
        hasattr(display_data, "units")
        and specifier[-1] in _number_specifiers
        and datatype is not str
    ):
        metadata["units"] = display_data.units
    if (
        hasattr(display_data, "precision")
        and not isnan(display_data.precision)
        and specifier[-1] in _float_specifiers
        and datatype is not int
    ):
        metadata["precision"] = display_data.precision
    if (limits := _limits_from_value(value)) and specifier[-1] in _number_specifiers:
        metadata["limits"] = limits
    # Get choices from display or value
    if datatype is str or issubclass(datatype, StrictEnum):
        if hasattr(display_data, "choices"):
            metadata["choices"] = display_data.choices
        elif hasattr(value_data, "choices"):
            metadata["choices"] = value_data.choices
    return metadata


class PvaConverter(Generic[SignalDatatypeT]):
    value_fields = ("value",)
    reading_fields = ("alarm", "timeStamp")

    def __init__(self, datatype: type[SignalDatatypeT]):
        self.datatype = datatype

    def value(self, value: Any) -> SignalDatatypeT:
        # Normally the value will be of the correct python type
        return value["value"]

    def write_value(self, value: Any) -> Any:
        # The pva library will do the conversion for us
        return value


class PvaIntConverter(PvaConverter[int]):
    def __init__(self):
        super().__init__(int)

    def value(self, value: Any) -> int:
        # Convert to an int
        return int(value["value"])


class PvaLongStringConverter(PvaConverter[str]):
    def __init__(self):
        super().__init__(str)

    def value(self, value: Any) -> Any:
        # Value here is a null terminated array of ascii codes.
        # We strip out the null terminator, and convert each code
        # to the corresponding char, joining into a string
        return value["value"].tobytes().rstrip(b"\0").decode()

    def write_value(self, value: Any) -> Any:
        # Inverse of reading - convert each character into it's ascii code,
        # put into a list, and add null terminator.
        return np.frombuffer(str(value).encode() + b"\0", dtype=np.int8)


class DisconnectedPvaConverter(PvaConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


class PvaNDArrayConverter(PvaConverter[SignalDatatypeT]):
    value_fields = ("value", "dimension")

    def _get_dimensions(self, value) -> list[int]:
        dimensions: list[Value] = value["dimension"]
        dims = [dim.size for dim in dimensions]
        # Note: dimensions in NTNDArray are in fortran-like order
        # with first index changing fastest.
        #
        # Therefore we need to reverse the order of the dimensions
        # here to get back to a more usual C-like order with the
        # last index changing fastest.
        return dims[::-1]

    def value(self, value: Any) -> SignalDatatypeT:
        dims = self._get_dimensions(value)
        return value["value"].reshape(dims)

    def write_value(self, value: Any) -> Any:
        # No clear use-case for writing directly to an NDArray, and some
        # complexities around flattening to 1-D - e.g. dimension-order.
        # Don't support this for now.
        raise TypeError("Writing to NDArray not supported")


class PvaEnumConverter(PvaConverter[str]):
    def __init__(
        self, datatype: type[str] = str, supported_values: Mapping[str, str] = {}
    ):
        self.supported_values = supported_values
        super().__init__(datatype)

    def value(self, value: Any) -> str:
        str_value = value["value"]["choices"][value["value"]["index"]]
        if self.supported_values:
            return self.supported_values[str_value]
        else:
            return str_value


class PvaEnumBoolConverter(PvaConverter[bool]):
    def __init__(self):
        super().__init__(bool)

    def value(self, value: Any) -> bool:
        return bool(value["value"]["index"])


class PvaTableConverter(PvaConverter[Table]):
    def value(self, value) -> Table:
        return self.datatype(**value["value"].todict())

    def write_value(self, value: BaseModel | dict[str, Any]) -> Any:
        if isinstance(value, self.datatype):
            return value.model_dump(mode="python")
        return value


# https://mdavidsaver.github.io/p4p/values.html
_float_specifiers = {"f", "d"}
_int_specifiers = {"b", "B", "h", "H", "i", "I", "l", "L"}
_number_specifiers = _float_specifiers.union(_int_specifiers)
_datatype_converter_from_typeid: dict[
    tuple[str, str], tuple[type[SignalDatatype], type[PvaConverter]]
] = {
    ("epics:nt/NTScalar:1.0", "?"): (bool, PvaConverter),
    ("epics:nt/NTScalar:1.0", "b"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "B"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "h"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "H"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "i"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "I"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "l"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "L"): (int, PvaConverter),
    ("epics:nt/NTScalar:1.0", "f"): (float, PvaConverter),
    ("epics:nt/NTScalar:1.0", "d"): (float, PvaConverter),
    ("epics:nt/NTScalar:1.0", "s"): (str, PvaConverter),
    ("epics:nt/NTEnum:1.0", "S"): (str, PvaEnumConverter),
    ("epics:nt/NTScalarArray:1.0", "a?"): (Array1D[np.bool_], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "ab"): (Array1D[np.int8], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "aB"): (Array1D[np.uint8], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "ah"): (Array1D[np.int16], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "aH"): (Array1D[np.uint16], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "ai"): (Array1D[np.int32], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "aI"): (Array1D[np.uint32], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "al"): (Array1D[np.int64], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "aL"): (Array1D[np.uint64], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "af"): (Array1D[np.float32], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "ad"): (Array1D[np.float64], PvaConverter),
    ("epics:nt/NTScalarArray:1.0", "as"): (Sequence[str], PvaConverter),
    ("epics:nt/NTTable:1.0", "S"): (Table, PvaTableConverter),
    ("epics:nt/NTNDArray:1.0", "v"): (np.ndarray, PvaNDArrayConverter),
    ("epics:nt/NTNDArray:1.0", "U"): (np.ndarray, PvaNDArrayConverter),
}


def _get_specifier(value: Value) -> str:
    typ = value.type("value").aspy()
    if isinstance(typ, tuple):
        return typ[0]
    else:
        return str(typ)


def make_converter(datatype: type | None, values: dict[str, Any]) -> PvaConverter:
    pv = list(values)[0]
    typeid = get_unique({k: v.getID() for k, v in values.items()}, "typeids")
    specifier = get_unique(
        {k: _get_specifier(v) for k, v in values.items()},
        "value type specifiers",
    )
    # Make the datatype canonical for the inference below
    if datatype == typing.Sequence[str]:
        datatype = Sequence[str]
    # Infer a datatype and converter from the typeid and specifier
    inferred_datatype, converter_cls = _datatype_converter_from_typeid[
        (typeid, specifier)
    ]
    # Some override cases
    if datatype is bool and typeid == "epics:nt/NTEnum:1.0":
        # Database can't do bools, so are often representated as enums of len 2
        pv_num_choices = get_unique(
            {k: len(v["value"]["choices"]) for k, v in values.items()},
            "number of choices",
        )
        if pv_num_choices != 2:
            raise TypeError(f"{pv} has {pv_num_choices} choices, can't map to bool")
        return PvaEnumBoolConverter()
    elif typeid == "epics:nt/NTEnum:1.0":
        pv_choices = get_unique(
            {k: tuple(v["value"]["choices"]) for k, v in values.items()}, "choices"
        )
        if enum_cls := get_enum_cls(datatype):
            # We were given an enum class, so make class from that
            return PvaEnumConverter(
                supported_values=get_supported_values(pv, enum_cls, pv_choices)
            )
        elif datatype in (None, str):
            # Still use the Enum converter, but make choices from what it has
            return PvaEnumConverter()
    elif (
        inferred_datatype is float
        and datatype is int
        and get_unique(
            {k: v["display"]["precision"] for k, v in values.items()}, "precision"
        )
        == 0
    ):
        # Allow int signals to represent float records when prec is 0
        return PvaIntConverter()
    elif inferred_datatype is str and (enum_cls := get_enum_cls(datatype)):
        # Allow strings to be used as enums until QSRV supports this
        return PvaConverter(str)
    elif inferred_datatype is Table and datatype and issubclass(datatype, Table):
        # Use a custom table class
        return PvaTableConverter(datatype)
    elif datatype in (None, inferred_datatype):
        # If datatype matches what we are given then allow it and use inferred converter
        return converter_cls(inferred_datatype)
    # Allow waveforms with FTVL=CHAR to be treated as str when requested
    elif datatype is str and inferred_datatype == Array1D[np.int8]:
        return PvaLongStringConverter()
    raise TypeError(
        f"{pv} with inferred datatype {format_datatype(inferred_datatype)}"
        f" from {typeid=} {specifier=}"
        f" cannot be coerced to {format_datatype(datatype)}"
    )


_context: Context | None = None


def context() -> Context:
    global _context
    if _context is None:
        _context = Context("pva", nt=False)

        @atexit.register
        def _del_ctxt():
            # If we don't do this we get messages like this on close:
            #   Error in sys.excepthook:
            #   Original exception was:
            global _context
            del _context

    return _context


async def pvget_with_timeout(pv: str, timeout: float) -> Any:
    try:
        return await asyncio.wait_for(context().get(pv), timeout=timeout)
    except asyncio.TimeoutError as exc:
        logger.debug(f"signal pva://{pv} timed out", exc_info=True)
        raise NotConnected(f"pva://{pv}") from exc


def _pva_request_string(fields: Sequence[str]) -> str:
    """Convert a list of requested fields into a PVA request string.

    This can be passed to p4p.
    """
    return f"field({','.join(fields)})"


class PvaSignalBackend(EpicsSignalBackend[SignalDatatypeT]):
    """Backend for a signal to interact with PVs over pva."""

    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        read_pv: str = "",
        write_pv: str = "",
    ):
        self.converter: PvaConverter = DisconnectedPvaConverter(float)
        self.initial_values: dict[str, Any] = {}
        self.subscription: Subscription | None = None
        super().__init__(datatype, read_pv, write_pv)

    def source(self, name: str, read: bool):
        return f"pva://{self.read_pv if read else self.write_pv}"

    async def _store_initial_value(self, pv: str, timeout: float):
        self.initial_values[pv] = await pvget_with_timeout(pv, timeout)

    async def connect(self, timeout: float):
        if self.read_pv != self.write_pv:
            # Different, need to connect both
            await wait_for_connection(
                read_pv=self._store_initial_value(self.read_pv, timeout=timeout),
                write_pv=self._store_initial_value(self.write_pv, timeout=timeout),
            )
        else:
            # The same, so only need to connect one
            await self._store_initial_value(self.read_pv, timeout=timeout)
        self.converter = make_converter(self.datatype, self.initial_values)

    def _make_reading(self, value: Any) -> Reading[SignalDatatypeT]:
        ts = value["timeStamp"]
        sv = value["alarm"]["severity"]
        return {
            "value": self.converter.value(value),
            "timestamp": ts["secondsPastEpoch"] + ts["nanoseconds"] * 1e-9,
            "alarm_severity": -1 if sv > 2 else sv,
        }

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        if value is None:
            write_value = self.initial_values[self.write_pv]["value"]
        else:
            write_value = self.converter.write_value(value)
        await context().put(self.write_pv, {"value": write_value}, wait=wait)

    async def get_datakey(self, source: str) -> DataKey:
        value = await context().get(self.read_pv)
        metadata = _metadata_from_value(self.converter.datatype, value)
        return make_datakey(
            self.converter.datatype, self.converter.value(value), source, metadata
        )

    async def get_reading(self) -> Reading:
        request = _pva_request_string(
            self.converter.value_fields + self.converter.reading_fields
        )
        value = await context().get(self.read_pv, request=request)
        return self._make_reading(value)

    async def get_value(self) -> SignalDatatypeT:
        request = _pva_request_string(self.converter.value_fields)
        value = await context().get(self.read_pv, request=request)
        return self.converter.value(value)

    async def get_setpoint(self) -> SignalDatatypeT:
        request = _pva_request_string(self.converter.value_fields)
        value = await context().get(self.write_pv, request=request)
        return self.converter.value(value)

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback and self.subscription:
            msg = "Cannot set a callback when one is already set"
            raise RuntimeError(msg)

        if self.subscription:
            self.subscription.close()
            self.subscription = None

        if callback:

            async def async_callback(v):
                callback(self._make_reading(v))

            request = _pva_request_string(
                self.converter.value_fields + self.converter.reading_fields
            )
            self.subscription = context().monitor(
                self.read_pv, async_callback, request=request
            )
