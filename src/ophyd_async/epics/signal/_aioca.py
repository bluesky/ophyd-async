import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
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
from epicscorelibs.ca import dbr
from event_model import DataKey
from event_model.documents.event_descriptor import Limits, LimitsRange

from ophyd_async.core import (
    Array1D,
    Callback,
    MockSignalBackend,
    SignalBackend,
    SignalConnector,
    SignalDatatype,
    SignalDatatypeT,
    SignalMetadata,
    get_enum_cls,
    get_unique,
    make_datakey,
    wait_for_connection,
)
from ophyd_async.core._protocol import Reading
from ophyd_async.core._utils import NotConnected

from ._common import format_datatype, get_supported_values


def _limits_from_augmented_value(value: AugmentedValue) -> Limits:
    def get_limits(limit: str) -> LimitsRange | None:
        low = getattr(value, f"lower_{limit}_limit", nan)
        high = getattr(value, f"upper_{limit}_limit", nan)
        if not (isnan(low) and isnan(high)):
            return LimitsRange(
                low=None if isnan(low) else low,
                high=None if isnan(high) else high,
            )

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
    value: AugmentedValue, metadata: SignalMetadata
) -> SignalMetadata:
    metadata = metadata.copy()
    if hasattr(value, "units"):
        metadata["units"] = value.units
    if hasattr(value, "precision") and not isnan(value.precision):
        metadata["precision"] = value.precision
    if limits := _limits_from_augmented_value(value):
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

    def write_value_and_dbr(self, value: Any) -> Any:
        # Add a null in here as this is what the commandline caput does
        # TODO: this should be in the server so check if it can be pushed to asyn
        return value + "\0"


class CaBoolConverter(CaConverter[bool]):
    def __init__(self):
        super().__init__(bool, dbr.DBR_SHORT)

    def value(self, value: AugmentedValue) -> bool:
        return bool(value)


class CaEnumConverter(CaConverter[str]):
    def __init__(self, supported_values: dict[str, str]):
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
    # Infer a datatype and converter from the dbr
    inferred_datatype, converter_cls = _datatype_converter_from_dbr[(pv_dbr, is_array)]
    # Some override cases
    if is_array and pv_dbr == dbr.DBR_CHAR and datatype is str:
        # Override waveform of chars to be treated as string
        return CaLongStrConverter()
    elif not is_array and pv_dbr == dbr.DBR_ENUM:
        pv_choices = get_unique(
            {k: tuple(v.enums) for k, v in values.items()}, "choices"
        )
        if datatype is bool:
            # Database can't do bools, so are often representated as enums of len 2
            if len(pv_choices) != 2:
                raise TypeError(f"{pv} has {pv_choices=}, can't map to bool")
            return CaBoolConverter()
        elif enum_cls := get_enum_cls(datatype):
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
        return CaConverter(int, pv_dbr)
    elif datatype in (None, inferred_datatype):
        # If datatype matches what we are given then allow it and use inferred converter
        return converter_cls(inferred_datatype, pv_dbr)
    if pv_dbr == dbr.DBR_ENUM:
        inferred_datatype = "str | SubsetEnum | StrictEnum"
    raise TypeError(
        f"{pv} with inferred datatype {format_datatype(inferred_datatype)}"
        f" cannot be coerced to {format_datatype(datatype)}"
    )


class CaSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        read_pv: str,
        write_pv: str,
        initial_values: dict[str, AugmentedValue],
    ):
        self._converter = make_converter(datatype, initial_values)
        self._read_pv = read_pv
        self._write_pv = write_pv
        self._initial_values = initial_values
        self._subscription: Subscription | None = None

    async def _caget(self, pv: str, format: Format) -> AugmentedValue:
        return await caget(
            pv, datatype=self._converter.read_dbr, format=format, timeout=None
        )

    def _make_reading(self, value: AugmentedValue) -> Reading[SignalDatatypeT]:
        return {
            "value": self._converter.value(value),
            "timestamp": value.timestamp,
            "alarm_severity": -1 if value.severity > 2 else value.severity,
        }

    async def put(self, value: SignalDatatypeT | None, wait=True, timeout=None):
        if value is None:
            write_value = self._initial_values[self._write_pv]
        else:
            write_value = self._converter.write_value(value)
        await caput(
            self._write_pv,
            write_value,
            datatype=self._converter.write_dbr,
            wait=wait,
            timeout=timeout,
        )

    async def get_datakey(self, source: str) -> DataKey:
        value = await self._caget(self._read_pv, FORMAT_CTRL)
        metadata = _metadata_from_augmented_value(value, self._converter.metadata)
        return make_datakey(
            self._converter.datatype, self._converter.value(value), source, metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        value = await self._caget(self._read_pv, FORMAT_TIME)
        return self._make_reading(value)

    async def get_value(self) -> SignalDatatypeT:
        value = await self._caget(self._read_pv, FORMAT_RAW)
        return self._converter.value(value)

    async def get_setpoint(self) -> SignalDatatypeT:
        value = await self._caget(self._write_pv, FORMAT_RAW)
        return self._converter.value(value)

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback:
            assert (
                not self._subscription
            ), "Cannot set a callback when one is already set"
            self._subscription = camonitor(
                self._read_pv,
                lambda v: callback(self._make_reading(v)),
                datatype=self._converter.read_dbr,
                format=FORMAT_TIME,
            )
        elif self._subscription:
            self._subscription.close()
            self._subscription = None


_tried_pyepics = False


def _use_pyepics_context_if_imported():
    global _tried_pyepics
    if not _tried_pyepics:
        ca = sys.modules.get("epics.ca", None)
        if ca:
            ca.use_initial_context()
        _tried_pyepics = True


@dataclass
class CaSignalConnector(SignalConnector[SignalDatatypeT]):
    datatype: type[SignalDatatypeT] | None
    read_pv: str
    write_pv: str

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        if mock:
            self.backend = MockSignalBackend(self.datatype)
        else:
            self.backend = await self.connect_epics(timeout)

    async def connect_epics(self, timeout: float) -> CaSignalBackend:
        _use_pyepics_context_if_imported()
        initial_values: dict[str, AugmentedValue] = {}

        async def store_initial_value(pv: str):
            try:
                initial_values[pv] = await caget(
                    pv, format=FORMAT_CTRL, timeout=timeout
                )
            except CANothing as exc:
                logging.debug(f"signal ca://{pv} timed out")
                raise NotConnected(f"ca://{pv}") from exc

        if self.read_pv != self.write_pv:
            # Different, need to connect both
            await wait_for_connection(
                read_pv=store_initial_value(self.read_pv),
                write_pv=store_initial_value(self.write_pv),
            )
        else:
            # The same, so only need to connect one
            await store_initial_value(self.read_pv)
        return CaSignalBackend(
            self.datatype, self.read_pv, self.write_pv, initial_values
        )

    def source(self, name: str) -> str:
        return f"ca://{self.read_pv}"
