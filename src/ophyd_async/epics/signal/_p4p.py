import asyncio
import atexit
import inspect
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from math import isnan, nan
from typing import Any, get_origin

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey
from event_model.documents.event_descriptor import Dtype
from p4p import Value
from p4p.client.asyncio import Context, Subscription
from pydantic import BaseModel

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    NotConnected,
    ReadingValueCallback,
    RuntimeSubsetEnum,
    SignalBackend,
    T,
    get_dtype,
    get_unique,
    is_pydantic_model,
    wait_for_connection,
)

from ._common import LimitPair, Limits, common_meta, get_supported_values

# https://mdavidsaver.github.io/p4p/values.html
specifier_to_dtype: dict[str, Dtype] = {
    "?": "integer",  # bool
    "b": "integer",  # int8
    "B": "integer",  # uint8
    "h": "integer",  # int16
    "H": "integer",  # uint16
    "i": "integer",  # int32
    "I": "integer",  # uint32
    "l": "integer",  # int64
    "L": "integer",  # uint64
    "f": "number",  # float32
    "d": "number",  # float64
    "s": "string",
}

specifier_to_np_dtype: dict[str, str] = {
    "?": "<i2",  # bool
    "b": "|i1",  # int8
    "B": "|u1",  # uint8
    "h": "<i2",  # int16
    "H": "<u2",  # uint16
    "i": "<i4",  # int32
    "I": "<u4",  # uint32
    "l": "<i8",  # int64
    "L": "<u8",  # uint64
    "f": "<f4",  # float32
    "d": "<f8",  # float64
    "s": "|S40",
}


def _data_key_from_value(
    source: str,
    value: Value,
    *,
    shape: list[int] | None = None,
    choices: list[str] | None = None,
    dtype: Dtype | None = None,
) -> DataKey:
    """
    Args:
        value (Value): Description of the the return type of a DB record
        shape: Optional override shape when len(shape) > 1
        choices: Optional list of enum choices to pass as metadata in the datakey
        dtype: Optional override dtype when AugmentedValue is ambiguous, e.g. booleans

    Returns:
        DataKey: A rich DataKey describing the DB record
    """
    shape = shape or []
    type_code = value.type().aspy("value")

    dtype = dtype or specifier_to_dtype[type_code]

    try:
        if isinstance(type_code, tuple):
            dtype_numpy = ""
            if type_code[1] == "enum_t":
                if dtype == "boolean":
                    dtype_numpy = "<i2"
                else:
                    for item in type_code[2]:
                        if item[0] == "choices":
                            dtype_numpy = specifier_to_np_dtype[item[1][1]]
        elif not type_code.startswith("a"):
            dtype_numpy = specifier_to_np_dtype[type_code]
        else:
            # Array type, use typecode of internal element
            dtype_numpy = specifier_to_np_dtype[type_code[1]]
    except KeyError:
        # Case where we can't determine dtype string from value
        dtype_numpy = ""

    display_data = getattr(value, "display", None)

    d = DataKey(
        source=source,
        dtype=dtype,
        # type ignore until https://github.com/bluesky/event-model/issues/308
        dtype_numpy=dtype_numpy,  # type: ignore
        shape=shape,
    )
    if display_data is not None:
        for key in common_meta:
            attr = getattr(display_data, key, nan)
            if isinstance(attr, str) or not isnan(attr):
                d[key] = attr

    if choices is not None:
        # type ignore until https://github.com/bluesky/event-model/issues/309
        d["choices"] = choices  # type: ignore

    if limits := _limits_from_value(value):
        # type ignore until https://github.com/bluesky/event-model/issues/309
        d["limits"] = limits  # type: ignore

    return d


def _limits_from_value(value: Value) -> Limits:
    def get_limits(
        substucture_name: str, low_name: str = "limitLow", high_name: str = "limitHigh"
    ) -> LimitPair:
        substructure = getattr(value, substucture_name, None)
        low = getattr(substructure, low_name, nan)
        high = getattr(substructure, high_name, nan)
        return LimitPair(
            low=None if isnan(low) else low, high=None if isnan(high) else high
        )

    return Limits(
        alarm=get_limits("valueAlarm", "lowAlarmLimit", "highAlarmLimit"),
        control=get_limits("control"),
        display=get_limits("display"),
        warning=get_limits("valueAlarm", "lowWarningLimit", "highWarningLimit"),
    )


class PvaConverter:
    def write_value(self, value):
        return value

    def value(self, value):
        return value["value"]

    def reading(self, value) -> Reading:
        ts = value["timeStamp"]
        sv = value["alarm"]["severity"]
        return {
            "value": self.value(value),
            "timestamp": ts["secondsPastEpoch"] + ts["nanoseconds"] * 1e-9,
            "alarm_severity": -1 if sv > 2 else sv,
        }

    def get_datakey(self, source: str, value) -> DataKey:
        return _data_key_from_value(source, value)

    def metadata_fields(self) -> list[str]:
        """
        Fields to request from PVA for metadata.
        """
        return ["alarm", "timeStamp"]

    def value_fields(self) -> list[str]:
        """
        Fields to request from PVA for the value.
        """
        return ["value"]


class PvaArrayConverter(PvaConverter):
    def get_datakey(self, source: str, value) -> DataKey:
        return _data_key_from_value(
            source, value, dtype="array", shape=[len(value["value"])]
        )


class PvaNDArrayConverter(PvaConverter):
    def metadata_fields(self) -> list[str]:
        return super().metadata_fields() + ["dimension"]

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

    def value(self, value):
        dims = self._get_dimensions(value)
        return value["value"].reshape(dims)

    def get_datakey(self, source: str, value) -> DataKey:
        dims = self._get_dimensions(value)
        return _data_key_from_value(source, value, dtype="array", shape=dims)

    def write_value(self, value):
        # No clear use-case for writing directly to an NDArray, and some
        # complexities around flattening to 1-D - e.g. dimension-order.
        # Don't support this for now.
        raise TypeError("Writing to NDArray not supported")


@dataclass
class PvaEnumConverter(PvaConverter):
    """To prevent issues when a signal is restarted and returns with different enum
    values or orders, we put treat an Enum signal as a string, and cache the
    choices on this class.
    """

    def __init__(self, choices: dict[str, str]):
        self.choices = tuple(choices.values())

    def write_value(self, value: Enum | str):
        if isinstance(value, Enum):
            return value.value
        else:
            return value

    def value(self, value):
        return self.choices[value["value"]["index"]]

    def get_datakey(self, source: str, value) -> DataKey:
        return _data_key_from_value(
            source, value, choices=list(self.choices), dtype="string"
        )


class PvaEmumBoolConverter(PvaConverter):
    def value(self, value):
        return bool(value["value"]["index"])

    def get_datakey(self, source: str, value) -> DataKey:
        return _data_key_from_value(source, value, dtype="boolean")


class PvaTableConverter(PvaConverter):
    def value(self, value):
        return value["value"].todict()

    def get_datakey(self, source: str, value) -> DataKey:
        # This is wrong, but defer until we know how to actually describe a table
        return _data_key_from_value(source, value, dtype="object")  # type: ignore


class PvaPydanticModelConverter(PvaConverter):
    def __init__(self, datatype: BaseModel):
        self.datatype = datatype

    def value(self, value: Value):
        return self.datatype(**value.todict())  # type: ignore

    def write_value(self, value: BaseModel | dict[str, Any]):
        if isinstance(value, self.datatype):  # type: ignore
            return value.model_dump(mode="python")  # type: ignore
        return value


class PvaDictConverter(PvaConverter):
    def reading(self, value) -> Reading:
        ts = time.time()
        value = value.todict()
        # Alarm severity is vacuously 0 for a table
        return {"value": value, "timestamp": ts, "alarm_severity": 0}

    def value(self, value: Value):
        return value.todict()

    def get_datakey(self, source: str, value) -> DataKey:
        raise NotImplementedError("Describing Dict signals not currently supported")

    def metadata_fields(self) -> list[str]:
        """
        Fields to request from PVA for metadata.
        """
        return []

    def value_fields(self) -> list[str]:
        """
        Fields to request from PVA for the value.
        """
        return []


class DisconnectedPvaConverter(PvaConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


def make_converter(datatype: type | None, values: dict[str, Any]) -> PvaConverter:
    pv = list(values)[0]
    typeid = get_unique({k: v.getID() for k, v in values.items()}, "typeids")
    typ = get_unique(
        {k: type(v.get("value")) for k, v in values.items()}, "value types"
    )
    if "NTScalarArray" in typeid and typ is list:
        # Waveform of strings, check we wanted this
        if datatype and datatype != Sequence[str]:
            raise TypeError(f"{pv} has type [str] not {datatype.__name__}")
        return PvaArrayConverter()
    elif "NTScalarArray" in typeid or "NTNDArray" in typeid:
        pv_dtype = get_unique(
            {k: v["value"].dtype for k, v in values.items()}, "dtypes"
        )
        # This is an array
        if datatype:
            # Check we wanted an array of this type
            dtype = get_dtype(datatype)
            if not dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not {datatype.__name__}")
            if dtype != pv_dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not [{dtype}]")
        if "NTNDArray" in typeid:
            return PvaNDArrayConverter()
        else:
            return PvaArrayConverter()
    elif "NTEnum" in typeid and datatype is bool:
        # Wanted a bool, but database represents as an enum
        pv_choices_len = get_unique(
            {k: len(v["value"]["choices"]) for k, v in values.items()},
            "number of choices",
        )
        if pv_choices_len != 2:
            raise TypeError(f"{pv} has {pv_choices_len} choices, can't map to bool")
        return PvaEmumBoolConverter()
    elif "NTEnum" in typeid:
        # This is an Enum
        pv_choices = get_unique(
            {k: tuple(v["value"]["choices"]) for k, v in values.items()}, "choices"
        )
        return PvaEnumConverter(get_supported_values(pv, datatype, pv_choices))
    elif "NTScalar" in typeid:
        if (
            typ is str
            and inspect.isclass(datatype)
            and issubclass(datatype, RuntimeSubsetEnum)
        ):
            return PvaEnumConverter(
                get_supported_values(pv, datatype, datatype.choices)  # type: ignore
            )
        elif datatype and not issubclass(typ, datatype):
            # Allow int signals to represent float records when prec is 0
            is_prec_zero_float = typ is float and (
                get_unique(
                    {k: v["display"]["precision"] for k, v in values.items()},
                    "precision",
                )
                == 0
            )
            if not (datatype is int and is_prec_zero_float):
                raise TypeError(f"{pv} has type {typ.__name__} not {datatype.__name__}")
        return PvaConverter()
    elif "NTTable" in typeid:
        if is_pydantic_model(datatype):
            return PvaPydanticModelConverter(datatype)  # type: ignore
        return PvaTableConverter()
    elif "structure" in typeid:
        return PvaDictConverter()
    else:
        raise TypeError(f"{pv}: Unsupported typeid {typeid}")


class PvaSignalBackend(SignalBackend[T]):
    _ctxt: Context | None = None

    _ALLOWED_DATATYPES = (
        bool,
        int,
        float,
        str,
        Sequence,
        np.ndarray,
        Enum,
        RuntimeSubsetEnum,
        BaseModel,
        dict,
    )

    @classmethod
    def datatype_allowed(cls, dtype: Any) -> bool:
        stripped_origin = get_origin(dtype) or dtype
        if dtype is None:
            return True
        return inspect.isclass(stripped_origin) and issubclass(
            stripped_origin, cls._ALLOWED_DATATYPES
        )

    def __init__(self, datatype: type[T] | None, read_pv: str, write_pv: str):
        self.datatype = datatype
        if not PvaSignalBackend.datatype_allowed(self.datatype):
            raise TypeError(f"Given datatype {self.datatype} unsupported in PVA.")

        self.read_pv = read_pv
        self.write_pv = write_pv
        self.initial_values: dict[str, Any] = {}
        self.converter: PvaConverter = DisconnectedPvaConverter()
        self.subscription: Subscription | None = None

    def source(self, name: str):
        return f"pva://{self.read_pv}"

    @property
    def ctxt(self) -> Context:
        if PvaSignalBackend._ctxt is None:
            PvaSignalBackend._ctxt = Context("pva", nt=False)

            @atexit.register
            def _del_ctxt():
                # If we don't do this we get messages like this on close:
                #   Error in sys.excepthook:
                #   Original exception was:
                PvaSignalBackend._ctxt = None

        return PvaSignalBackend._ctxt

    async def _store_initial_value(self, pv, timeout: float = DEFAULT_TIMEOUT):
        try:
            self.initial_values[pv] = await asyncio.wait_for(
                self.ctxt.get(pv), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            logging.debug(f"signal pva://{pv} timed out", exc_info=True)
            raise NotConnected(f"pva://{pv}") from exc

    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
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

    async def put(self, value: T | None, wait=True, timeout=None):
        if value is None:
            write_value = self.initial_values[self.write_pv]
        else:
            write_value = self.converter.write_value(value)
        coro = self.ctxt.put(self.write_pv, {"value": write_value}, wait=wait)
        try:
            await asyncio.wait_for(coro, timeout)
        except asyncio.TimeoutError as exc:
            logging.debug(
                f"signal pva://{self.write_pv} timed out \
                          put value: {write_value}",
                exc_info=True,
            )
            raise NotConnected(f"pva://{self.write_pv}") from exc

    async def get_datakey(self, source: str) -> DataKey:
        value = await self.ctxt.get(self.read_pv)
        return self.converter.get_datakey(source, value)

    def _pva_request_string(self, fields: list[str]) -> str:
        """
        Converts a list of requested fields into a PVA request string which can be
        passed to p4p.
        """
        return f"field({','.join(fields)})"

    async def get_reading(self) -> Reading:
        request: str = self._pva_request_string(
            self.converter.value_fields() + self.converter.metadata_fields()
        )
        value = await self.ctxt.get(self.read_pv, request=request)
        return self.converter.reading(value)

    async def get_value(self) -> T:
        request: str = self._pva_request_string(self.converter.value_fields())
        value = await self.ctxt.get(self.read_pv, request=request)
        return self.converter.value(value)

    async def get_setpoint(self) -> T:
        value = await self.ctxt.get(self.write_pv, "field(value)")
        return self.converter.value(value)

    def set_callback(self, callback: ReadingValueCallback[T] | None) -> None:
        if callback:
            assert (
                not self.subscription
            ), "Cannot set a callback when one is already set"

            async def async_callback(v):
                callback(self.converter.reading(v), self.converter.value(v))

            request: str = self._pva_request_string(
                self.converter.value_fields() + self.converter.metadata_fields()
            )

            self.subscription = self.ctxt.monitor(
                self.read_pv, async_callback, request=request
            )
        else:
            if self.subscription:
                self.subscription.close()
            self.subscription = None
