import asyncio
import time

import numpy as np
from asyncio import CancelledError

from abc import abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from tango import AttributeInfoEx, AttrDataFormat, CmdArgType, EventType, GreenMode, DevState, CommandInfo
from tango.asyncio import DeviceProxy
from tango.utils import is_int, is_float, is_bool, is_str, is_binary, is_array

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
def get_pyton_type(tango_type) -> tuple[bool, T, str]:
    array = is_array(tango_type)
    if is_int(tango_type, True):
        return array, int, "integer"
    if is_float(tango_type, True):
        return array, float, "number"
    if is_bool(tango_type, True):
        return array, bool, "integer"
    if is_str(tango_type, True):
        return array, str, "string"
    if is_binary(tango_type, True):
        return array, list[str], "string"
    if tango_type == CmdArgType.DevEnum:
        return array, Enum, "string"
    if tango_type == CmdArgType.DevState:
        return array, CmdArgType.DevState, "string"
    if tango_type == CmdArgType.DevUChar:
        return array, int, "integer"
    if tango_type == CmdArgType.DevVoid:
        return array, None, "string"
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
    async def get_config(self) -> Union[AttributeInfoEx, CommandInfo]:
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
                rid = self._proxy.write_attribute_asynch(self._name, value, green_mode=GreenMode.Synchronous)
                await asyncio.sleep(timeout)
                self._proxy.write_attribute_reply(rid, green_mode=GreenMode.Synchronous)
            else:
                self._proxy.write_attribute(self._name, value, green_mode=GreenMode.Synchronous)
        else:
            await self._proxy.write_attribute(self._name, value)

    # --------------------------------------------------------------------
    async def get_config(self) -> AttributeInfoEx:
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
class CommandProxy(TangoProxy):

    support_events = False
    _last_reading = dict(value=None, timestamp=0, alarm_severity=0)

    # --------------------------------------------------------------------
    async def get(self) -> T:
        return self._last_reading["value"]

    # --------------------------------------------------------------------
    async def put(self, value: Optional[T], wait: bool = True, timeout: Optional[float] = None) -> None:
        if wait:
            if timeout:
                rid = self._proxy.command_inout_asynch(self._name, value, green_mode=GreenMode.Synchronous)
                await asyncio.sleep(timeout)
                val = self._proxy.command_inout_reply(rid, green_mode=GreenMode.Synchronous)
            else:
                val = self._proxy.command_inout(self._name, value, green_mode=GreenMode.Synchronous)
        else:
            val = await self._proxy.command_inout(self._name, value)

        self._last_reading = dict(value=val, timestamp=time.time(), alarm_severity=0)

    # --------------------------------------------------------------------
    async def get_config(self) -> CommandInfo:
        return await self._proxy.get_command_config(self._name)

    # --------------------------------------------------------------------
    async def get_reading(self) -> Reading:
        return self._last_reading


# --------------------------------------------------------------------
def get_dtype_extendet(datatype):
    # DevState tango type does not have numpy equivalents
    dtype = get_dtype(datatype)
    if dtype == np.object_:
        print(f"{datatype.__args__[1].__args__[0]=}, {datatype.__args__[1].__args__[0]==Enum}")
        if datatype.__args__[1].__args__[0] == DevState:
            dtype = CmdArgType.DevState
    return dtype


# --------------------------------------------------------------------
def get_pv_descriptor(datatype: Optional[Type], pv: str, pvs_config: Dict[str, Union[AttributeInfoEx, CommandInfo]]) -> dict:
    pvs_dtype = {}
    for pv_name, config in pvs_config.items():
        if isinstance(config, AttributeInfoEx):
            _, dtype, descr = get_pyton_type(config.data_type)
            pvs_dtype[pv_name] = config.data_format, dtype, descr
        elif isinstance(config, CommandInfo):
            if config.in_type != CmdArgType.DevVoid and \
                    config.out_type != CmdArgType.DevVoid and \
                    config.in_type != config.out_type:
                raise RuntimeError("Commands with different in and out dtypes are not supported")
            array, dtype, descr = get_pyton_type(config.in_type if config.in_type != CmdArgType.DevVoid else config.out_type)
            pvs_dtype[pv_name] = AttrDataFormat.SPECTRUM if array else AttrDataFormat.SCALAR, dtype, descr
        else:
            raise RuntimeError(f"Unknown config type: {type(config)}")
    pv_format, pv_dtype, pv_dtype_desc = get_unique(pvs_dtype, "typeids")

    # tango commands are limited in functionality: they do not have info about shape and Enum labels
    pv_config = list(pvs_config.values())[0]
    max_x = pv_config.max_dim_x if hasattr(pv_config, "max_dim_x") else np.Inf
    max_y = pv_config.max_dim_x if hasattr(pv_config, "max_dim_y") else np.Inf
    is_attr = hasattr(pv_config, "enum_labels")
    pv_choices = list(pv_config.enum_labels) if is_attr else []

    if pv_format in [AttrDataFormat.SPECTRUM, AttrDataFormat.IMAGE]:
        # This is an array
        if datatype:
            print(f"{datatype=}")
            # Check we wanted an array of this type
            dtype = get_dtype_extendet(datatype)
            if not dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not {datatype.__name__}")
            if dtype != pv_dtype:
                raise TypeError(f"{pv} has type [{pv_dtype}] not [{dtype}]")

        if pv_format == AttrDataFormat.SPECTRUM:
            return dict(source=pv, dtype="array", shape=[max_x])
        elif pv_format == AttrDataFormat.IMAGE:
            return dict(source=pv, dtype="array", shape=[max_x, max_y])

    else:
        if pv_dtype in (Enum, CmdArgType.DevState):
            if pv_dtype == CmdArgType.DevState:
                pv_choices = list(DevState.names.keys())

            if datatype:
                if not issubclass(datatype, (Enum, DevState)):
                    raise TypeError(f"{pv} has type Enum not {datatype.__name__}")
                if pv_dtype == Enum and is_attr:
                    choices = tuple(v.name for v in datatype)
                    if set(choices) != set(pv_choices):
                        raise TypeError(f"{pv} has choices {pv_choices} not {choices}")
            return dict(source=pv, dtype="string", shape=[], choices=pv_choices)
        else:
            if datatype and not issubclass(pv_dtype, datatype):
                raise TypeError(f"{pv} has type {pv_dtype.__name__} not {datatype.__name__}")
            return dict(source=pv, dtype=pv_dtype_desc, shape=[])


# --------------------------------------------------------------------
async def get_tango_pv(full_trl: str, device_proxy: Optional[DeviceProxy]) -> TangoProxy:
    device_trl, pv_name = full_trl.rsplit('/', 1)
    device_proxy = device_proxy or await DeviceProxy(device_trl)
    if pv_name in device_proxy.get_attribute_list():
        return AttributeProxy(device_proxy, pv_name)
    if pv_name in device_proxy.get_command_list():
        return CommandProxy(device_proxy, pv_name)
    if pv_name in device_proxy.get_pipe_list():
        raise NotImplemented("Pipes are not supported")

    raise RuntimeError(f"{pv_name} cannot be found in {device_proxy.name()}")


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
        self.pv_configs: Dict[str, AttributeConfig] = {}
        self.source = f"{self.read_pv}"
        self.descriptor: Descriptor = {}  # type: ignore
        self.eid: Optional[int] = None

    # --------------------------------------------------------------------
    async def _connect_and_store_config(self, pv):
        try:
            self.proxies[pv] = await get_tango_pv(pv, self.proxies[pv])
            self.pv_configs[pv] = await self.proxies[pv].get_config()
        except CancelledError:
            raise NotConnected(self.source)

    # --------------------------------------------------------------------
    async def connect(self):
        if self.read_pv != self.write_pv:
            # Different, need to connect both
            await wait_for_connection(
                read_pv=self._connect_and_store_config(self.read_pv),
                write_pv=self._connect_and_store_config(self.write_pv),
            )
        else:
            # The same, so only need to connect one
            await self._connect_and_store_config(self.read_pv)
        self.descriptor = get_pv_descriptor(self.datatype, self.read_pv, self.pv_configs)

    # --------------------------------------------------------------------
    async def put(self, write_value: Optional[T], wait=True, timeout=None):
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