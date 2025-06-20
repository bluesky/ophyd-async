from abc import abstractmethod
from collections.abc import Sequence
from typing import Generic, TypedDict, TypeVar, get_origin

import numpy as np
from bluesky.protocols import Reading
from event_model import DataKey, Dtype, Limits

from ophyd_async.core._utils import (
    Callback,
    EnumTypes,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    get_enum_cls,
)

from ._table import Table

DTypeScalar_co = TypeVar("DTypeScalar_co", covariant=True, bound=np.generic)
"""A numpy dtype like [](#numpy.float64)."""


# To be a 1D array shape should really be tuple[int], but np.array()
# currently produces tuple[int, ...] even when it has 1D input args
# https://github.com/numpy/numpy/issues/28077#issuecomment-2566485178
Array1D = np.ndarray[tuple[int, ...], np.dtype[DTypeScalar_co]]
"""A type alias for a 1D numpy array with a specific scalar data type.

E.g. `Array1D[np.float64]` is a 1D numpy array of 64-bit floats."""

Primitive = bool | int | float | str
SignalDatatype = (
    Primitive
    | EnumTypes
    | Array1D[np.bool_]
    | Array1D[np.int8]
    | Array1D[np.uint8]
    | Array1D[np.int16]
    | Array1D[np.uint16]
    | Array1D[np.int32]
    | Array1D[np.uint32]
    | Array1D[np.int64]
    | Array1D[np.uint64]
    | Array1D[np.float32]
    | Array1D[np.float64]
    | np.ndarray
    | Sequence[str]
    | Sequence[StrictEnum]
    | Sequence[SubsetEnum]
    | Sequence[SupersetEnum]
    | Table
)
"""The supported [](#Signal) datatypes:

- A python primitive [](#bool), [](#int), [](#float), [](#str)
- An [](#EnumTypes) subclass
- A fixed datatype [](#Array1D) of numpy bool, signed and unsigned integers or float
- A [](#numpy.ndarray) which can change dimensions and datatype at runtime
- A sequence of [](#str)
- A sequence of [](#EnumTypes) subclasses
- A [](#Table) subclass
"""
# TODO: These typevars will not be needed when we drop python 3.11
# as you can do MyConverter[SignalType: SignalTypeUnion]:
# rather than MyConverter(Generic[SignalType])
PrimitiveT = TypeVar("PrimitiveT", bound=Primitive)
SignalDatatypeT = TypeVar("SignalDatatypeT", bound=SignalDatatype)
"""A typevar for a [](#SignalDatatype)."""
SignalDatatypeV = TypeVar("SignalDatatypeV", bound=SignalDatatype)
EnumT = TypeVar("EnumT", bound=EnumTypes)
TableT = TypeVar("TableT", bound=Table)


class SignalBackend(Generic[SignalDatatypeT]):
    """A read/write/monitor backend for a Signals."""

    def __init__(self, datatype: type[SignalDatatypeT] | None):
        self.datatype = datatype

    @abstractmethod
    def source(self, name: str, read: bool) -> str:
        """Return source of signal.

        :param name: The name of the signal, which can be used or discarded.
        :param read: True if we want the source for reading, False if writing.
        """

    @abstractmethod
    async def connect(self, timeout: float):
        """Connect to underlying hardware."""

    @abstractmethod
    async def put(self, value: SignalDatatypeT | None, wait: bool):
        """Put a value to the PV, if wait then wait for completion."""

    @abstractmethod
    async def get_datakey(self, source: str) -> DataKey:
        """Metadata like source, dtype, shape, precision, units."""

    @abstractmethod
    async def get_reading(self) -> Reading[SignalDatatypeT]:
        """Return the current value, timestamp and severity."""

    @abstractmethod
    async def get_value(self) -> SignalDatatypeT:
        """Return the current value."""

    @abstractmethod
    async def get_setpoint(self) -> SignalDatatypeT:
        """Return the point that a signal was requested to move to."""

    @abstractmethod
    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""


_primitive_dtype: dict[type[Primitive], Dtype] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


class SignalMetadata(TypedDict, total=False):
    """Metadata for a signal. No field is required."""

    limits: Limits
    """The control, display, warning and alarm limits for a numeric datatype."""

    choices: list[str]
    """The choice of possible values for an enum datatype."""

    precision: int
    """The number of digits after the decimal place to display for a float datatype."""

    units: str
    """The engineering units of the value for a numeric datatype."""


def _datakey_dtype(datatype: type[SignalDatatype]) -> Dtype:
    if (
        datatype is np.ndarray
        or get_origin(datatype) in (Sequence, np.ndarray)
        or issubclass(datatype, Table)
    ):
        return "array"
    elif issubclass(datatype, EnumTypes):
        return "string"
    elif issubclass(datatype, Primitive):
        return _primitive_dtype[datatype]
    else:
        raise TypeError(f"Can't make dtype for {datatype}")


def _datakey_dtype_numpy(
    datatype: type[SignalDatatypeT], value: SignalDatatypeT
) -> np.dtype:
    if isinstance(value, np.ndarray):
        # The value already has a dtype, use that
        return value.dtype
    elif (
        get_origin(datatype) is Sequence
        or datatype is str
        or issubclass(datatype, EnumTypes)
    ):
        # TODO: use np.dtypes.StringDType when we can use in structured arrays
        # https://github.com/numpy/numpy/issues/25693
        return np.dtype("S40")
    elif isinstance(value, Table):
        return value.numpy_dtype()
    elif issubclass(datatype, Primitive):
        return np.dtype(datatype)
    else:
        raise TypeError(f"Can't make dtype_numpy for {datatype}")


def _datakey_shape(value: SignalDatatype) -> list[int | None]:
    if type(value) in _primitive_dtype or isinstance(value, EnumTypes):
        return []
    elif isinstance(value, np.ndarray):
        return list(value.shape)
    elif isinstance(value, Sequence | Table):
        return [len(value)]
    else:
        raise TypeError(f"Can't make shape for {value}")


def make_datakey(
    datatype: type[SignalDatatypeT],
    value: SignalDatatypeT,
    source: str,
    metadata: SignalMetadata,
) -> DataKey:
    """Make a DataKey for a given datatype."""
    dtn = _datakey_dtype_numpy(datatype, value)
    return DataKey(
        dtype=_datakey_dtype(datatype),
        shape=_datakey_shape(value),
        # Ignore until https://github.com/bluesky/event-model/issues/308
        dtype_numpy=dtn.descr if len(dtn.descr) > 1 else dtn.str,  # type: ignore
        source=source,
        **metadata,
    )


def make_metadata(
    datatype: type[SignalDatatypeT] | None,
    units: str | None = None,
    precision: int | None = None,
) -> SignalMetadata:
    metadata: SignalMetadata = {}
    if units is not None:
        metadata["units"] = units
    if precision is not None:
        metadata["precision"] = precision
    if enum_cls := get_enum_cls(datatype):
        metadata["choices"] = [v.value for v in enum_cls]
    return metadata
