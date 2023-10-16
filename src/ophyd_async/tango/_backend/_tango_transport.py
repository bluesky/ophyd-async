import asyncio
import numpy as np
from asyncio import CancelledError

from abc import abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from tango import AttributeConfig, AttrDataFormat, CmdArgType, EventType, GreenMode, DevState
from tango.asyncio import DeviceProxy
from tango.utils import is_int, is_float, is_bool, is_str, is_binary

from bluesky.protocols import Descriptor, Dtype, Reading

from ophyd_async.core import (
    NotConnected,
    ReadingValueCallback,
    SignalBackend,
    T,
    get_dtype,
    get_unique,
    wait_for_connection,
)


# --------------------------------------------------------------------
def get_pyton_type(tango_type):
    if is_int(tango_type):
        return int, "integer"
    if is_float(tango_type):
        return float, "number"
    if is_bool(tango_type):
        return bool, "integer"
    if is_str(tango_type):
        return str, "string"
    if is_binary(tango_type):
        return list[str], "string"
    if tango_type == CmdArgType.DevEnum:
        return Enum, "string"
    if tango_type == CmdArgType.DevState:
        return CmdArgType.DevState, "string"
    if tango_type == CmdArgType.DevUChar:
        return int, "integer"
    if tango_type == CmdArgType.DevVoid:
        return None, "string"
    raise TypeError("Unknown TangoType")


# --------------------------------------------------------------------
class TangoProxy:

    support_events = False

    def __init__(self, device_proxy: DeviceProxy, name: str):
        self._proxy = device_proxy
        self._name = name

    # --------------------------------------------------------------------
    @abstractmethod
    async def get(self) -> T:
        """Get value from PV"""

    # --------------------------------------------------------------------
    @abstractmethod
    async def put(self, value: Optional[T], wait: bool=True, timeout: Optional[float]=None) -> None:
        """Get value from PV"""

    # --------------------------------------------------------------------
    @abstractmethod
    async def get_config(self) -> AttributeConfig:
        """Get value from PV"""

    # --------------------------------------------------------------------
    @abstractmethod
    async def get_reading(self) -> Reading:
        """Get value from PV"""

    # --------------------------------------------------------------------
    def has_subscription(self) -> bool:
        """indicates, that this pv already subscribed"""

    # --------------------------------------------------------------------
    @abstractmethod
    def subscribe_callback(self, callback: Optional[ReadingValueCallback]):
        """subscribe tango CHANGE event to callback"""

    # --------------------------------------------------------------------
    @abstractmethod
    def unsubscribe_callback(self, callback: Optional[ReadingValueCallback]):
        """delete CHANGE event subscription"""


# --------------------------------------------------------------------
class AttributeProxy(TangoProxy):

    support_events = True
    _event_callback = None
    _eid = None

    # --------------------------------------------------------------------
    async def get(self) -> T:
        attr = await self._proxy.read_attribute(self._name)
        return attr.value

    # --------------------------------------------------------------------
    async def put(self, value: Optional[T], wait: bool = True, timeout: Optional[float] = None) -> None:
        if wait:
            if timeout:
                id = self._proxy.write_attribute_asynch(self._name, value, green_mode=GreenMode.Synchronous)
                await asyncio.sleep(timeout)
                self._proxy.write_attribute_reply(id, green_mode=GreenMode.Synchronous)
            else:
                self._proxy.write_attribute(self._name, value, green_mode=GreenMode.Synchronous)
        else:
            await self._proxy.write_attribute(self._name, value, wait=wait, timeout=timeout)

    # --------------------------------------------------------------------
    async def get_config(self) -> AttributeConfig:
        return await self._proxy.get_attribute_config(self._name)

    # --------------------------------------------------------------------
    async def get_reading(self) -> Reading:
        attr = await self._proxy.read_attribute(self._name)
        return dict(
            value=attr.value,
            timestamp=attr.time.totime(),
            alarm_severity=attr.quality,
        )

    # --------------------------------------------------------------------
    def has_subscription(self) -> bool:
        return bool(self._eid)

    # --------------------------------------------------------------------
    def subscribe_callback(self, callback: Optional[ReadingValueCallback]):
        """add user callack to delete CHANGE event subscription"""
        self._event_callback = callback
        self._eid = self._proxy.subscribe_event(self._name, EventType.CHANGE_EVENT, self._event_processor)

    # --------------------------------------------------------------------
    def unsubscribe_callback(self, eid: int):
        self._proxy.unsubscribe_event(self._eid)
        self._eid = None
        self._event_callback = None

    # --------------------------------------------------------------------
    def _event_processor(self, event):
        if not event.err:
            value = event.attr_value.value
            reading = dict(value=value,
                           timestamp=event.get_date().totime(),
                           alarm_severity=event.attr_value.quality)

            self._event_callback(reading, value)


# --------------------------------------------------------------------
async def get_tango_pv(full_trl: str, device_proxy: Optional[DeviceProxy]) -> TangoProxy:
    device_trl, pv_name = full_trl.rsplit('/', 1)
    device_proxy = device_proxy or await DeviceProxy(device_trl)
    if pv_name in device_proxy.get_attribute_list():
        return AttributeProxy(device_proxy, pv_name)


# --------------------------------------------------------------------
def get_dtype_extendet(datatype):
    # DevState tango type does not have numpy equivalents
    dtype = get_dtype(datatype)
    if dtype == np.object_:
        if datatype.__args__[1].__args__[0] == DevState:
            dtype = CmdArgType.DevState
    return dtype


# --------------------------------------------------------------------
def get_descriptor(datatype: Optional[Type], pv: str, attr_config: Dict[str, AttributeConfig]) -> dict:

    pv_dtype, pv_dtype_desc = get_unique({k: get_pyton_type(v.data_type) for k, v in attr_config.items()}, "typeids")
    attr_config = list(attr_config.values())[0]

    if attr_config.data_format in [AttrDataFormat.SPECTRUM, AttrDataFormat.IMAGE]:
        # This is an array
        if datatype:
            # Check we wanted an array of this type
            dtype = get_dtype_extendet(datatype)
            if not dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not {datatype.__name__}")
            if dtype != pv_dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not [{dtype}]")

        if attr_config.data_format == AttrDataFormat.SPECTRUM:
            return dict(source=pv, dtype="array", shape=[attr_config.max_dim_x])
        else:
            return dict(source=pv, dtype="array", shape=[attr_config.max_dim_y, attr_config.max_dim_x])

    else:
        if pv_dtype in (Enum, CmdArgType.DevState):
            if pv_dtype == Enum:
                pv_choices = list(attr_config.enum_labels)
            else:
                pv_choices = list(DevState.names.keys())

            if datatype:
                if not issubclass(datatype, (Enum, DevState)):
                    raise TypeError(f"{pv} has type Enum not {datatype.__name__}")
                if pv_dtype == Enum:
                    choices = tuple(v.name for v in datatype)
                    if set(choices) != set(pv_choices):
                        raise TypeError(f"{pv} has choices {pv_choices} not {choices}")
            return dict(source=pv, dtype="string", shape=[], choices=pv_choices)
        else:
            if datatype and not issubclass(pv_dtype, datatype):
                raise TypeError(f"{pv} has type {pv_dtype.__name__} not {datatype.__name__}")
            return dict(source=pv, dtype=pv_dtype_desc, shape=[])


# --------------------------------------------------------------------
class TangoTransport(SignalBackend[T]):

    def __init__(self,
                 datatype: Optional[Type[T]],
                 read_pv: str,
                 write_pv: str,
                 device_proxy: Optional[DeviceProxy] = None):
        self.datatype = datatype
        self.read_pv = read_pv
        self.write_pv = write_pv
        self.proxies: Dict[str, TangoProxy] = {read_pv: device_proxy, write_pv: device_proxy}
        self.initial_readings: Dict[str, Any] = {}
        self.pv_configs: Dict[str, AttributeConfig] = {}
        self.source = f"{self.read_pv}"
        self.descriptor: Descriptor = {}  # type: ignore
        self.eid: Optional[int] = None

    # --------------------------------------------------------------------
    async def _connect_and_store_initial_value(self, pv):
        try:
            self.proxies[pv] = await get_tango_pv(pv, self.proxies[pv])
            self.initial_readings[pv] = await self.proxies[pv].get()
            self.pv_configs[pv] = await self.proxies[pv].get_config()
        except CancelledError:
            raise NotConnected(self.source)

    # --------------------------------------------------------------------
    async def connect(self):
        if self.read_pv != self.write_pv:
            # Different, need to connect both
            await wait_for_connection(
                read_pv=self._connect_and_store_initial_value(self.read_pv),
                write_pv=self._connect_and_store_initial_value(self.write_pv),
            )
        else:
            # The same, so only need to connect one
            await self._connect_and_store_initial_value(self.read_pv)
        self.descriptor = get_descriptor(self.datatype, self.read_pv, self.pv_configs)

    # --------------------------------------------------------------------
    async def put(self, write_value: Optional[T], wait=True, timeout=None):
        if write_value is None:
            write_value = self.initial_readings[self.write_pv]["value"]

        await self.proxies[self.write_pv].put(write_value, wait, timeout)

    # --------------------------------------------------------------------
    async def get_descriptor(self) -> Descriptor:
        return self.descriptor

    # --------------------------------------------------------------------
    async def get_reading(self) -> Reading:
        return await self.proxies[self.read_pv].get_reading()

    # --------------------------------------------------------------------
    async def get_value(self) -> T:
        return await self.proxies[self.write_pv].get()

    # --------------------------------------------------------------------
    def set_callback(self, callback: Optional[ReadingValueCallback]) -> None:
        assert self.proxies[self.read_pv].support_events, f"{self.source} does not support events"

        if callback:
            assert (not self.proxies[self.read_pv].has_subscription()), "Cannot set a callback when one is already set"
            self.eid = self.proxies[self.read_pv].subscribe_callback(callback)

        else:
            if self.eid:
                self.proxies[self.read_pv].unsubscribe_callback(self.eid)
            self.eid = None