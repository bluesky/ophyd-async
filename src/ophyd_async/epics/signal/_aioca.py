import inspect
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from math import isnan, nan
from typing import Any, get_origin

import numpy as np
from aioca import (
    FORMAT_CTRL,
    FORMAT_RAW,
    FORMAT_TIME,
    CANothing,
    Subscription,
    caget,
    camonitor,
    caput,
)
from aioca.types import AugmentedValue, Dbr, Format
from bluesky.protocols import Reading
from epicscorelibs.ca import dbr
from event_model import DataKey
from event_model.documents.event_descriptor import Dtype

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    NotConnected,
    ReadingValueCallback,
    RuntimeSubsetEnum,
    SignalBackend,
    T,
    get_dtype,
    get_unique,
    wait_for_connection,
)

from ._common import LimitPair, Limits, common_meta, get_supported_values

dbr_to_dtype: dict[Dbr, Dtype] = {
    dbr.DBR_STRING: "string",
    dbr.DBR_SHORT: "integer",
    dbr.DBR_FLOAT: "number",
    dbr.DBR_CHAR: "string",
    dbr.DBR_LONG: "integer",
    dbr.DBR_DOUBLE: "number",
}


def _data_key_from_augmented_value(
    value: AugmentedValue,
    *,
    choices: list[str] | None = None,
    dtype: Dtype | None = None,
) -> DataKey:
    """Use the return value of get with FORMAT_CTRL to construct a DataKey
    describing the signal. See docstring of AugmentedValue for expected
    value fields by DBR type.

    Args:
        value (AugmentedValue): Description of the the return type of a DB record
        choices: Optional list of enum choices to pass as metadata in the datakey
        dtype: Optional override dtype when AugmentedValue is ambiguous, e.g. booleans

    Returns:
        DataKey: A rich DataKey describing the DB record
    """
    source = f"ca://{value.name}"
    assert value.ok, f"Error reading {source}: {value}"

    scalar = value.element_count == 1
    dtype = dtype or dbr_to_dtype[value.datatype]  # type: ignore

    dtype_numpy = np.dtype(dbr.DbrCodeToType[value.datatype].dtype).descr[0][1]

    d = DataKey(
        source=source,
        dtype=dtype if scalar else "array",
        # Ignore until https://github.com/bluesky/event-model/issues/308
        dtype_numpy=dtype_numpy,  # type: ignore
        # strictly value.element_count >= len(value)
        shape=[] if scalar else [len(value)],
    )
    for key in common_meta:
        attr = getattr(value, key, nan)
        if isinstance(attr, str) or not isnan(attr):
            d[key] = attr

    if choices is not None:
        d["choices"] = choices  # type: ignore

    if limits := _limits_from_augmented_value(value):
        d["limits"] = limits  # type: ignore

    return d


def _limits_from_augmented_value(value: AugmentedValue) -> Limits:
    def get_limits(limit: str) -> LimitPair:
        low = getattr(value, f"lower_{limit}_limit", nan)
        high = getattr(value, f"upper_{limit}_limit", nan)
        return LimitPair(
            low=None if isnan(low) else low, high=None if isnan(high) else high
        )

    return Limits(
        alarm=get_limits("alarm"),
        control=get_limits("ctrl"),
        display=get_limits("disp"),
        warning=get_limits("warning"),
    )


@dataclass
class CaConverter:
    read_dbr: Dbr | None
    write_dbr: Dbr | None

    def write_value(self, value) -> Any:
        return value

    def value(self, value: AugmentedValue):
        # for channel access ca_xxx classes, this
        # invokes __pos__ operator to return an instance of
        # the builtin base class
        return +value  # type: ignore

    def reading(self, value: AugmentedValue) -> Reading:
        return {
            "value": self.value(value),
            "timestamp": value.timestamp,
            "alarm_severity": -1 if value.severity > 2 else value.severity,
        }

    def get_datakey(self, value: AugmentedValue) -> DataKey:
        return _data_key_from_augmented_value(value)


class CaLongStrConverter(CaConverter):
    def __init__(self):
        return super().__init__(dbr.DBR_CHAR_STR, dbr.DBR_CHAR_STR)

    def write_value(self, value: str):
        # Add a null in here as this is what the commandline caput does
        # TODO: this should be in the server so check if it can be pushed to asyn
        return value + "\0"


class CaArrayConverter(CaConverter):
    def value(self, value: AugmentedValue):
        return np.array(value, copy=False)


@dataclass
class CaEnumConverter(CaConverter):
    """To prevent issues when a signal is restarted and returns with different enum
    values or orders, we put treat an Enum signal as a string, and cache the
    choices on this class.
    """

    choices: dict[str, str]

    def write_value(self, value: Enum | str):
        if isinstance(value, Enum):
            return value.value
        else:
            return value

    def value(self, value: AugmentedValue):
        return self.choices[value]  # type: ignore

    def get_datakey(self, value: AugmentedValue) -> DataKey:
        # Sometimes DBR_TYPE returns as String, must pass choices still
        return _data_key_from_augmented_value(value, choices=list(self.choices.keys()))


@dataclass
class CaBoolConverter(CaConverter):
    def value(self, value: AugmentedValue) -> bool:
        return bool(value)

    def get_datakey(self, value: AugmentedValue) -> DataKey:
        return _data_key_from_augmented_value(value, dtype="boolean")


class DisconnectedCaConverter(CaConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


def make_converter(
    datatype: type | None, values: dict[str, AugmentedValue]
) -> CaConverter:
    pv = list(values)[0]
    pv_dbr = get_unique({k: v.datatype for k, v in values.items()}, "datatypes")
    is_array = bool([v for v in values.values() if v.element_count > 1])
    if is_array and datatype is str and pv_dbr == dbr.DBR_CHAR:
        # Override waveform of chars to be treated as string
        return CaLongStrConverter()
    elif is_array and pv_dbr == dbr.DBR_STRING:
        # Waveform of strings, check we wanted this
        if datatype:
            datatype_dtype = get_dtype(datatype)
            if not datatype_dtype or not np.can_cast(datatype_dtype, np.str_):
                raise TypeError(f"{pv} has type [str] not {datatype.__name__}")
        return CaArrayConverter(pv_dbr, None)
    elif is_array:
        pv_dtype = get_unique({k: v.dtype for k, v in values.items()}, "dtypes")  # type: ignore
        # This is an array
        if datatype:
            # Check we wanted an array of this type
            dtype = get_dtype(datatype)
            if not dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not {datatype.__name__}")
            if dtype != pv_dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not [{dtype}]")
        return CaArrayConverter(pv_dbr, None)  # type: ignore
    elif pv_dbr == dbr.DBR_ENUM and datatype is bool:
        # Database can't do bools, so are often representated as enums,
        # CA can do int
        pv_choices_len = get_unique(
            {k: len(v.enums) for k, v in values.items()}, "number of choices"
        )
        if pv_choices_len != 2:
            raise TypeError(f"{pv} has {pv_choices_len} choices, can't map to bool")
        return CaBoolConverter(dbr.DBR_SHORT, dbr.DBR_SHORT)
    elif pv_dbr == dbr.DBR_ENUM:
        # This is an Enum
        pv_choices = get_unique(
            {k: tuple(v.enums) for k, v in values.items()}, "choices"
        )
        supported_values = get_supported_values(pv, datatype, pv_choices)
        return CaEnumConverter(dbr.DBR_STRING, None, supported_values)
    else:
        value = list(values.values())[0]
        # Done the dbr check, so enough to check one of the values
        if datatype and not isinstance(value, datatype):
            # Allow int signals to represent float records when prec is 0
            is_prec_zero_float = (
                isinstance(value, float)
                and get_unique({k: v.precision for k, v in values.items()}, "precision")
                == 0
            )
            if not (datatype is int and is_prec_zero_float):
                raise TypeError(
                    f"{pv} has type {type(value).__name__.replace('ca_', '')} "
                    + f"not {datatype.__name__}"
                )
    return CaConverter(pv_dbr, None)  # type: ignore


_tried_pyepics = False


def _use_pyepics_context_if_imported():
    global _tried_pyepics
    if not _tried_pyepics:
        ca = sys.modules.get("epics.ca", None)
        if ca:
            ca.use_initial_context()
        _tried_pyepics = True


class CaSignalBackend(SignalBackend[T]):
    _ALLOWED_DATATYPES = (
        bool,
        int,
        float,
        str,
        Sequence,
        Enum,
        RuntimeSubsetEnum,
        np.ndarray,
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
        if not CaSignalBackend.datatype_allowed(self.datatype):
            raise TypeError(f"Given datatype {self.datatype} unsupported in CA.")
        self.read_pv = read_pv
        self.write_pv = write_pv
        self.initial_values: dict[str, AugmentedValue] = {}
        self.converter: CaConverter = DisconnectedCaConverter(None, None)
        self.subscription: Subscription | None = None

    def source(self, name: str):
        return f"ca://{self.read_pv}"

    async def _store_initial_value(self, pv, timeout: float = DEFAULT_TIMEOUT):
        try:
            self.initial_values[pv] = await caget(
                pv, format=FORMAT_CTRL, timeout=timeout
            )
        except CANothing as exc:
            logging.debug(f"signal ca://{pv} timed out")
            raise NotConnected(f"ca://{pv}") from exc

    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        _use_pyepics_context_if_imported()
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
        await caput(
            self.write_pv,
            write_value,
            datatype=self.converter.write_dbr,
            wait=wait,
            timeout=timeout,
        )

    async def _caget(self, format: Format) -> AugmentedValue:
        return await caget(
            self.read_pv,
            datatype=self.converter.read_dbr,
            format=format,
            timeout=None,
        )

    async def get_datakey(self, source: str) -> DataKey:
        value = await self._caget(FORMAT_CTRL)
        return self.converter.get_datakey(value)

    async def get_reading(self) -> Reading:
        value = await self._caget(FORMAT_TIME)
        return self.converter.reading(value)

    async def get_value(self) -> T:
        value = await self._caget(FORMAT_RAW)
        return self.converter.value(value)

    async def get_setpoint(self) -> T:
        value = await caget(
            self.write_pv,
            datatype=self.converter.read_dbr,
            format=FORMAT_RAW,
            timeout=None,
        )
        return self.converter.value(value)

    def set_callback(self, callback: ReadingValueCallback[T] | None) -> None:
        if callback:
            assert (
                not self.subscription
            ), "Cannot set a callback when one is already set"
            self.subscription = camonitor(
                self.read_pv,
                lambda v: callback(self.converter.reading(v), self.converter.value(v)),
                datatype=self.converter.read_dbr,
                format=FORMAT_TIME,
            )
        else:
            if self.subscription:
                self.subscription.close()
            self.subscription = None
