import asyncio
import atexit
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from bluesky.protocols import Descriptor, Dtype, Reading
from p4p import Value
from p4p.client.asyncio import Context, Subscription

from ophyd_async.core import (
    ReadingValueCallback,
    SignalBackend,
    T,
    get_dtype,
    get_unique,
    wait_for_connection,
)
from ophyd_async.core.utils import DEFAULT_TIMEOUT, NotConnected

from .common import get_supported_enum_class

# https://mdavidsaver.github.io/p4p/values.html
specifier_to_dtype: Dict[str, Dtype] = {
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


class PvaConverter:
    def write_value(self, value):
        return value

    def value(self, value):
        return value["value"]

    def reading(self, value):
        ts = value["timeStamp"]
        sv = value["alarm"]["severity"]
        return {
            "value": self.value(value),
            "timestamp": ts["secondsPastEpoch"] + ts["nanoseconds"] * 1e-9,
            "alarm_severity": -1 if sv > 2 else sv,
        }

    def descriptor(self, source: str, value) -> Descriptor:
        dtype = specifier_to_dtype[value.type().aspy("value")]
        return {"source": source, "dtype": dtype, "shape": []}

    def metadata_fields(self) -> List[str]:
        """
        Fields to request from PVA for metadata.
        """
        return ["alarm", "timeStamp"]

    def value_fields(self) -> List[str]:
        """
        Fields to request from PVA for the value.
        """
        return ["value"]


class PvaArrayConverter(PvaConverter):
    def descriptor(self, source: str, value) -> Descriptor:
        return {"source": source, "dtype": "array", "shape": [len(value["value"])]}


class PvaNDArrayConverter(PvaConverter):
    def metadata_fields(self) -> List[str]:
        return super().metadata_fields() + ["dimension"]

    def _get_dimensions(self, value) -> List[int]:
        dimensions: List[Value] = value["dimension"]
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

    def descriptor(self, source: str, value) -> Descriptor:
        dims = self._get_dimensions(value)
        return {"source": source, "dtype": "array", "shape": dims}

    def write_value(self, value):
        # No clear use-case for writing directly to an NDArray, and some
        # complexities around flattening to 1-D - e.g. dimension-order.
        # Don't support this for now.
        raise TypeError("Writing to NDArray not supported")


@dataclass
class PvaEnumConverter(PvaConverter):
    enum_class: Type[Enum]

    def write_value(self, value: Union[Enum, str]):
        if isinstance(value, Enum):
            return value.value
        else:
            return value

    def value(self, value):
        return list(self.enum_class)[value["value"]["index"]]

    def descriptor(self, source: str, value) -> Descriptor:
        choices = [e.value for e in self.enum_class]
        return {"source": source, "dtype": "string", "shape": [], "choices": choices}


class PvaEnumBoolConverter(PvaConverter):
    def value(self, value):
        return value["value"]["index"]

    def descriptor(self, source: str, value) -> Descriptor:
        return {"source": source, "dtype": "integer", "shape": []}


class PvaTableConverter(PvaConverter):
    def value(self, value):
        return value["value"].todict()

    def descriptor(self, source: str, value) -> Descriptor:
        # This is wrong, but defer until we know how to actually describe a table
        return {"source": source, "dtype": "object", "shape": []}  # type: ignore


class PvaDictConverter(PvaConverter):
    def reading(self, value):
        ts = time.time()
        value = value.todict()
        # Alarm severity is vacuously 0 for a table
        return {"value": value, "timestamp": ts, "alarm_severity": 0}

    def value(self, value: Value):
        return value.todict()

    def descriptor(self, source: str, value) -> Descriptor:
        raise NotImplementedError("Describing Dict signals not currently supported")

    def metadata_fields(self) -> List[str]:
        """
        Fields to request from PVA for metadata.
        """
        return []

    def value_fields(self) -> List[str]:
        """
        Fields to request from PVA for the value.
        """
        return []


class DisconnectedPvaConverter(PvaConverter):
    def __getattribute__(self, __name: str) -> Any:
        raise NotImplementedError("No PV has been set as connect() has not been called")


def make_converter(datatype: Optional[Type], values: Dict[str, Any]) -> PvaConverter:
    pv = list(values)[0]
    typeid = get_unique({k: v.getID() for k, v in values.items()}, "typeids")
    typ = get_unique(
        {k: type(v.get("value")) for k, v in values.items()}, "value types"
    )
    if "NTScalarArray" in typeid and typ == list:
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
        return PvaEnumBoolConverter()
    elif "NTEnum" in typeid:
        # This is an Enum
        pv_choices = get_unique(
            {k: tuple(v["value"]["choices"]) for k, v in values.items()}, "choices"
        )
        return PvaEnumConverter(get_supported_enum_class(pv, datatype, pv_choices))
    elif "NTScalar" in typeid:
        if datatype and not issubclass(typ, datatype):
            raise TypeError(f"{pv} has type {typ.__name__} not {datatype.__name__}")
        return PvaConverter()
    elif "NTTable" in typeid:
        return PvaTableConverter()
    elif "structure" in typeid:
        return PvaDictConverter()
    else:
        raise TypeError(f"{pv}: Unsupported typeid {typeid}")


class PvaSignalBackend(SignalBackend[T]):
    _ctxt: Optional[Context] = None

    def __init__(self, datatype: Optional[Type[T]], read_pv: str, write_pv: str):
        self.datatype = datatype
        self.read_pv = read_pv
        self.write_pv = write_pv
        self.initial_values: Dict[str, Any] = {}
        self.converter: PvaConverter = DisconnectedPvaConverter()
        self.subscription: Optional[Subscription] = None

    @property
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

    async def put(self, value: Optional[T], wait=True, timeout=None):
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

    async def get_descriptor(self, source: str) -> Descriptor:
        value = await self.ctxt.get(self.read_pv)
        return self.converter.descriptor(source, value)

    def _pva_request_string(self, fields: List[str]) -> str:
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

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
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
