import logging
import sys
import typing
from collections.abc import Mapping, Sequence
from functools import cache
from math import isnan, nan
from typing import Any, Generic, cast

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
from event_model import DataKey, Limits, LimitsRange

from ophyd_async.core import (
    Array1D,
    Callback,
    NotConnected,
    SignalDatatype,
    SignalDatatypeT,
    SignalMetadata,
    get_enum_cls,
    get_unique,
    make_datakey,
    wait_for_connection,
)

from ._util import EpicsSignalBackend, format_datatype, get_supported_values

logger = logging.getLogger("ophyd_async")


def _limits_from_augmented_value(value: AugmentedValue) -> Limits:
    def get_limits(limit: str) -> LimitsRange | None:
        low = getattr(value, f"lower_{limit}_limit", nan)
        high = getattr(value, f"upper_{limit}_limit", nan)
        if not (isnan(low) and isnan(high)) and not high == low == 0:
            return LimitsRange(
                low=None if isnan(low) else low,
                high=None if isnan(high) else high,
            )
        return None

    limits = Limits()
    if limits_range := get_limits("alarm"):
        limits["alarm"] = limits_range
    if limits_range := get_limits("ctrl"):
        limits["control"] = limits_range
    if limits_range := get_limits("disp"):
        limits["display"] = limits_range
    if limits_range := get_limits("warning"):
        limits["warning"] = limits_range
    return limits


def _metadata_from_augmented_value(
    datatype: type[SignalDatatypeT] | None,
    value: AugmentedValue,
    metadata: SignalMetadata,
) -> SignalMetadata:
    metadata = metadata.copy()
    if hasattr(value, "units") and datatype not in (str, bool):
        metadata["units"] = value.units
    if (
        hasattr(value, "precision")
        and not isnan(value.precision)
        and datatype is not int
    ):
        metadata["precision"] = value.precision
    if (limits := _limits_from_augmented_value(value)) and datatype is not bool:
        metadata["limits"] = limits
    return metadata


class CaConverter(Generic[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT],
        read_dbr: Dbr,
        write_dbr: Dbr | None = None,
        metadata: SignalMetadata | None = None,
    ):
        self.datatype = datatype
        self.read_dbr: Dbr = read_dbr
        self.write_dbr: Dbr | None = write_dbr
        self.metadata = metadata or SignalMetadata()

    def write_value(self, value: Any) -> Any:
        # The ca library will do the conversion for us
        return value

    def value(self, value: AugmentedValue) -> SignalDatatypeT:
        # for channel access ca_xxx classes, this
        # invokes __pos__ operator to return an instance of
        # the builtin base class
        return +value  # type: ignore


class DisconnectedCaConverter(CaConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


class CaIntConverter(CaConverter[int]):
    def value(self, value: AugmentedValue) -> int:
        return int(value)  # type: ignore


class CaArrayConverter(CaConverter[np.ndarray]):
    def value(self, value: AugmentedValue) -> np.ndarray:
        # A less expensive conversion
        return np.array(value, copy=False)


class CaSequenceStrConverter(CaConverter[Sequence[str]]):
    def value(self, value: AugmentedValue) -> Sequence[str]:
        return [str(v) for v in value]  # type: ignore


class CaLongStrConverter(CaConverter[str]):
    def __init__(self):
        super().__init__(str, dbr.DBR_CHAR_STR, dbr.DBR_CHAR_STR)

    def write_value(self, value: Any) -> Any:
        # Add a null in here as this is what the commandline caput does
        # TODO: this should be in the server so check if it can be pushed to asyn
        return value + "\0"


class CaBoolConverter(CaConverter[bool]):
    def __init__(self):
        super().__init__(bool, dbr.DBR_SHORT)

    def value(self, value: AugmentedValue) -> bool:
        return bool(value)


class CaEnumConverter(CaConverter[str]):
    def __init__(self, supported_values: Mapping[str, str]):
        self.supported_values = supported_values
        super().__init__(
            str, dbr.DBR_STRING, metadata=SignalMetadata(choices=list(supported_values))
        )

    def value(self, value: AugmentedValue) -> str:
        return self.supported_values[str(value)]


_datatype_converter_from_dbr: dict[
    tuple[Dbr, bool], tuple[type[SignalDatatype], type[CaConverter]]
] = {
    (dbr.DBR_STRING, False): (str, CaConverter),
    (dbr.DBR_SHORT, False): (int, CaConverter),
    (dbr.DBR_FLOAT, False): (float, CaConverter),
    (dbr.DBR_ENUM, False): (str, CaConverter),
    (dbr.DBR_CHAR, False): (int, CaConverter),
    (dbr.DBR_LONG, False): (int, CaConverter),
    (dbr.DBR_DOUBLE, False): (float, CaConverter),
    (dbr.DBR_STRING, True): (Sequence[str], CaSequenceStrConverter),
    (dbr.DBR_SHORT, True): (Array1D[np.int16], CaArrayConverter),
    (dbr.DBR_FLOAT, True): (Array1D[np.float32], CaArrayConverter),
    (dbr.DBR_ENUM, True): (Sequence[str], CaSequenceStrConverter),
    (dbr.DBR_CHAR, True): (Array1D[np.uint8], CaArrayConverter),
    (dbr.DBR_LONG, True): (Array1D[np.int32], CaArrayConverter),
    (dbr.DBR_DOUBLE, True): (Array1D[np.float64], CaArrayConverter),
}


def make_converter(
    datatype: type | None, values: dict[str, AugmentedValue]
) -> CaConverter:
    pv = list(values)[0]
    pv_dbr = cast(
        Dbr, get_unique({k: v.datatype for k, v in values.items()}, "datatypes")
    )
    is_array = bool([v for v in values.values() if v.element_count > 1])
    # Make the datatype canonical for the inference below
    if datatype == typing.Sequence[str]:
        datatype = Sequence[str]
    # Infer a datatype and converter from the dbr
    inferred_datatype, converter_cls = _datatype_converter_from_dbr[(pv_dbr, is_array)]
    # Some override cases
    if is_array and pv_dbr == dbr.DBR_CHAR and datatype is str:
        # Override waveform of chars to be treated as string
        return CaLongStrConverter()
    elif not is_array and datatype is bool and pv_dbr == dbr.DBR_ENUM:
        # Database can't do bools, so are often representated as enums of len 2
        pv_num_choices = get_unique(
            {k: len(v.enums) for k, v in values.items()}, "number of choices"
        )
        if pv_num_choices != 2:
            raise TypeError(f"{pv} has {pv_num_choices} choices, can't map to bool")
        return CaBoolConverter()
    elif not is_array and pv_dbr == dbr.DBR_ENUM:
        pv_choices = get_unique(
            {k: tuple(v.enums) for k, v in values.items()}, "choices"
        )
        if enum_cls := get_enum_cls(datatype):
            # If explicitly requested then check
            return CaEnumConverter(get_supported_values(pv, enum_cls, pv_choices))
        elif datatype in (None, str):
            # Drop to string for safety, but retain choices as metadata
            return CaConverter(
                str,
                dbr.DBR_STRING,
                metadata=SignalMetadata(choices=list(pv_choices)),
            )
    elif (
        inferred_datatype is float
        and datatype is int
        and get_unique({k: v.precision for k, v in values.items()}, "precision") == 0
    ):
        # Allow int signals to represent float records when prec is 0
        return CaIntConverter(int, pv_dbr)
    elif datatype in (None, inferred_datatype):
        # If datatype matches what we are given then allow it and use inferred converter
        return converter_cls(inferred_datatype, pv_dbr)
    if pv_dbr == dbr.DBR_ENUM:
        inferred_datatype = "str | SubsetEnum | StrictEnum"
    raise TypeError(
        f"{pv} with inferred datatype {format_datatype(inferred_datatype)}"
        f" cannot be coerced to {format_datatype(datatype)}"
    )


# Cached call to avoid repeated initialization attempts
@cache
def _use_pyepics_context_if_imported():
    """Sets up the pyepics context if the module is imported."""
    ca = sys.modules.get("epics.ca", None)
    if ca:
        ca.use_initial_context()


class CaSignalBackend(EpicsSignalBackend[SignalDatatypeT]):
    """Backend for a signal to interact with PVs over channel access."""

    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        read_pv: str = "",
        write_pv: str = "",
        all_updates: bool = True,
    ):
        self.converter: CaConverter = DisconnectedCaConverter(float, dbr.DBR_DOUBLE)
        self.initial_values: dict[str, AugmentedValue] = {}
        self.subscription: Subscription | None = None
        self._all_updates = all_updates
        super().__init__(datatype, read_pv, write_pv)

    def source(self, name: str, read: bool):
        return f"ca://{self.read_pv if read else self.write_pv}"

    async def _store_initial_value(self, pv: str, timeout: float):
        try:
            self.initial_values[pv] = await caget(
                pv, format=FORMAT_CTRL, timeout=timeout
            )
        except CANothing as exc:
            logger.debug(f"signal ca://{pv} timed out")
            raise NotConnected(f"ca://{pv}") from exc

    async def connect(self, timeout: float):
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

    async def _caget(self, pv: str, format: Format) -> AugmentedValue:
        return await caget(
            pv, datatype=self.converter.read_dbr, format=format, timeout=None
        )

    def _make_reading(self, value: AugmentedValue) -> Reading[SignalDatatypeT]:
        return {
            "value": self.converter.value(value),
            "timestamp": value.timestamp,
            "alarm_severity": -1 if value.severity > 2 else value.severity,
        }

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        if value is None:
            write_value = self.initial_values[self.write_pv]
        else:
            write_value = self.converter.write_value(value)
        try:
            await caput(
                self.write_pv,
                write_value,
                datatype=self.converter.write_dbr,
                wait=wait,
                timeout=None,
            )
        except CANothing as exc:
            # If we ran into a write error, check to see if there is a list
            # of valid choices, and if the value we tried to write is in that list.
            valid_choices = self.converter.metadata.get("choices")
            if valid_choices:
                if value not in valid_choices:
                    msg = (
                        f"{value} is not a valid choice for {self.write_pv}, "
                        f"valid choices: {self.converter.metadata.get('choices')}"
                    )
                    raise ValueError(msg) from exc
                raise
            raise

    async def get_datakey(self, source: str) -> DataKey:
        value = await self._caget(self.read_pv, FORMAT_CTRL)
        metadata = _metadata_from_augmented_value(
            self.datatype, value, self.converter.metadata
        )
        return make_datakey(
            self.converter.datatype, self.converter.value(value), source, metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        value = await self._caget(self.read_pv, FORMAT_TIME)
        return self._make_reading(value)

    async def get_value(self) -> SignalDatatypeT:
        value = await self._caget(self.read_pv, FORMAT_RAW)
        return self.converter.value(value)

    async def get_setpoint(self) -> SignalDatatypeT:
        value = await self._caget(self.write_pv, FORMAT_RAW)
        return self.converter.value(value)

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback and self.subscription:
            msg = "Cannot set a callback when one is already set"
            raise RuntimeError(msg)

        if self.subscription:
            self.subscription.close()
            self.subscription = None

        if callback:
            self.subscription = camonitor(
                self.read_pv,
                lambda v: callback(self._make_reading(v)),
                datatype=self.converter.read_dbr,
                format=FORMAT_TIME,
                all_updates=self._all_updates,
            )
