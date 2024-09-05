import asyncio
import functools
import time
from abc import abstractmethod
from asyncio import CancelledError
from enum import Enum
from typing import Dict, Optional, Type, Union

import numpy as np
from bluesky.protocols import DataKey, Descriptor, Reading

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    NotConnected,
    ReadingValueCallback,
    SignalBackend,
    T,
    get_dtype,
    get_unique,
    wait_for_connection,
)
from tango import (
    AttrDataFormat,
    AttributeInfoEx,
    CmdArgType,
    CommandInfo,
    DevFailed,
    DevState,
    EventType,
)
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import (
    AsyncioExecutor,
    get_global_executor,
    set_global_executor,
)
from tango.utils import is_array, is_binary, is_bool, is_float, is_int, is_str

# time constant to wait for timeout
A_BIT = 1e-5


def ensure_proper_executor(func):
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        current_executor = get_global_executor()
        if not current_executor.in_executor_context():
            set_global_executor(AsyncioExecutor())
        return await func(self, *args, **kwargs)

    return wrapper


def get_python_type(tango_type) -> tuple[bool, T, str]:
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


class TangoProxy:
    support_events = True

    def __init__(self, device_proxy: DeviceProxy, name: str):
        self._proxy = device_proxy
        self._name = name

    async def connect(self):
        """perform actions after proxy is connected, e.g. checks if signal
        can be subscribed"""

    @abstractmethod
    async def get(self) -> T:
        """Get value from TRL"""

    @abstractmethod
    async def get_w_value(self) -> T:
        """Get last written value from TRL"""

    @abstractmethod
    async def put(
        self, value: Optional[T], wait: bool = True, timeout: Optional[float] = None
    ) -> None:
        """Put value to TRL"""

    @abstractmethod
    async def get_config(self) -> Union[AttributeInfoEx, CommandInfo]:
        """Get TRL config async"""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """Get reading from TRL"""

    def has_subscription(self) -> bool:
        """indicates, that this trl already subscribed"""

    @abstractmethod
    def subscribe_callback(self, callback: Optional[ReadingValueCallback]):
        """subscribe tango CHANGE event to callback"""

    @abstractmethod
    def unsubscribe_callback(self):
        """delete CHANGE event subscription"""

    @abstractmethod
    def set_polling(
        self,
        allow_polling: bool = True,
        polling_period: float = 0.1,
        abs_change=None,
        rel_change=None,
    ):
        """Set polling parameters"""


class AttributeProxy(TangoProxy):
    _callback = None
    support_events = True
    _eid = None
    _poll_task = None
    _abs_change = None
    _rel_change = 0.1
    _polling_period = 0.1
    _allow_polling = False
    exception = None
    _last_reading = {"value": None, "timestamp": 0, "alarm_severity": 0}

    async def connect(self) -> None:
        try:
            eid = await self._proxy.subscribe_event(
                self._name, EventType.CHANGE_EVENT, self._event_processor
            )
            await self._proxy.unsubscribe_event(eid)
            self.support_events = True
        except Exception:
            pass

    @ensure_proper_executor
    async def get(self) -> T:
        attr = await self._proxy.read_attribute(self._name)
        return attr.value

    @ensure_proper_executor
    async def get_w_value(self) -> T:
        attr = await self._proxy.read_attribute(self._name)
        return attr.w_value

    @ensure_proper_executor
    async def put(
        self, value: Optional[T], wait: bool = True, timeout: Optional[float] = None
    ) -> None or AsyncStatus:
        if wait:
            try:

                async def _write():
                    return await self._proxy.write_attribute(self._name, value)

                task = asyncio.create_task(_write())
                await asyncio.wait_for(task, timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(f"{self._name} attr put failed: Timeout")
            except DevFailed as e:
                raise RuntimeError(f"{self._name} device failure: {e.args[0].desc}")

        else:
            rid = await self._proxy.write_attribute_asynch(self._name, value)

            async def wait_for_reply(rd, to):
                start_time = time.time() if to else None
                while True:
                    try:
                        await self._proxy.write_attribute_reply(rd)
                        break
                    except DevFailed as exc:
                        if exc.args[0].reason == "API_AsynReplyNotArrived":
                            await asyncio.sleep(A_BIT)
                            if to and time.time() - start_time > to:
                                raise TimeoutError(
                                    f"{self._name} attr put failed:" f" Timeout"
                                )
                        else:
                            raise RuntimeError(
                                f"{self._name} device failure:" f" {exc.args[0].desc}"
                            )

            return AsyncStatus(wait_for_reply(rid, timeout))

    @ensure_proper_executor
    async def get_config(self) -> AttributeInfoEx:
        return await self._proxy.get_attribute_config(self._name)

    @ensure_proper_executor
    async def get_reading(self) -> Reading:
        attr = await self._proxy.read_attribute(self._name)
        reading = Reading(
            value=attr.value, timestamp=attr.time.totime(), alarm_severity=attr.quality
        )
        self._last_reading = reading
        return reading

    def has_subscription(self) -> bool:
        return bool(self._callback)

    def subscribe_callback(self, callback: Optional[ReadingValueCallback]):
        # If the attribute supports events, then we can subscribe to them
        # If the callback is not a callable, then we raise an error
        if callback is not None and not callable(callback):
            raise RuntimeError("Callback must be a callable")

        self._callback = callback
        if self.support_events:
            """add user callback to CHANGE event subscription"""
            if not self._eid:
                self._eid = self._proxy.subscribe_event(
                    self._name,
                    EventType.CHANGE_EVENT,
                    self._event_processor,
                    green_mode=False,
                )
        elif self._allow_polling:
            """start polling if no events supported"""
            if self._callback is not None:

                async def _poll():
                    while True:
                        try:
                            await self.poll()
                        except RuntimeError as e:
                            self.exception = f"Error in polling: {e}"
                            await asyncio.sleep(1)

                self._poll_task = asyncio.create_task(_poll())
        else:
            self.unsubscribe_callback()
            raise RuntimeError(
                f"Cannot set event for {self._name}. "
                "Cannot set a callback on an attribute that does not support events and"
                " for which polling is disabled."
            )

    def unsubscribe_callback(self):
        if self._eid:
            self._proxy.unsubscribe_event(self._eid, green_mode=False)
            self._eid = None
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
            if self._callback is not None:
                # Call the callback with the last reading
                try:
                    self._callback(self._last_reading, self._last_reading["value"])
                except TypeError:
                    pass
        self._callback = None

    def _event_processor(self, event):
        if not event.err:
            value = event.attr_value.value
            reading = {
                "value": value,
                "timestamp": event.get_date().totime(),
                "alarm_severity": event.attr_value.quality,
            }
            self._callback(reading, value)

    async def poll(self):
        """
        Poll the attribute and call the callback if the value has changed by more
        than the absolute or relative change. This function is used when an attribute
        that does not support events is cached or a callback is passed to it.
        """
        try:
            last_reading = await self.get_reading()
            flag = 0
            # Initial reading
            if self._callback is not None:
                self._callback(last_reading, last_reading["value"])
        except Exception as e:
            raise RuntimeError(f"Could not poll the attribute: {e}")

        try:
            # If the value is a number, we can check for changes
            if isinstance(last_reading["value"], (int, float)):
                while True:
                    await asyncio.sleep(self._polling_period)
                    reading = await self.get_reading()
                    if reading is None or reading["value"] is None:
                        continue
                    diff = abs(reading["value"] - last_reading["value"])
                    if self._abs_change is not None and diff >= abs(self._abs_change):
                        if self._callback is not None:
                            self._callback(reading, reading["value"])
                            flag = 0

                    elif (
                        self._rel_change is not None
                        and diff >= self._rel_change * abs(last_reading["value"])
                    ):
                        if self._callback is not None:
                            self._callback(reading, reading["value"])
                            flag = 0

                    else:
                        flag = (flag + 1) % 4
                        if flag == 0 and self._callback is not None:
                            self._callback(reading, reading["value"])

                    last_reading = reading.copy()
                    if self._callback is None:
                        break
            # If the value is not a number, we can only poll
            else:
                while True:
                    await asyncio.sleep(self._polling_period)
                    flag = (flag + 1) % 4
                    if flag == 0:
                        reading = await self.get_reading()
                        if reading is None or reading["value"] is None:
                            continue
                        if isinstance(reading["value"], np.ndarray):
                            if not np.array_equal(
                                reading["value"], last_reading["value"]
                            ):
                                if self._callback is not None:
                                    self._callback(reading, reading["value"])
                                else:
                                    break
                        else:
                            if reading["value"] != last_reading["value"]:
                                if self._callback is not None:
                                    self._callback(reading, reading["value"])
                                else:
                                    break
                        last_reading = reading.copy()
        except Exception as e:
            raise RuntimeError(f"Could not poll the attribute: {e}")

    def set_polling(
        self,
        allow_polling: bool = False,
        polling_period: float = 0.5,
        abs_change=None,
        rel_change=0.1,
    ):
        """
        Set the polling parameters.
        """
        self._allow_polling = allow_polling
        self._polling_period = polling_period
        self._abs_change = abs_change
        self._rel_change = rel_change


class CommandProxy(TangoProxy):
    support_events = True
    _last_reading = {"value": None, "timestamp": 0, "alarm_severity": 0}

    async def get(self) -> T:
        return self._last_reading["value"]

    async def get_w_value(self) -> T:
        return self._last_reading["value"]

    @ensure_proper_executor
    async def put(
        self, value: Optional[T], wait: bool = True, timeout: Optional[float] = None
    ) -> None or AsyncStatus:
        if wait:
            try:
                # val = await self._proxy.command_inout(self._name, value)
                async def _put():
                    return await self._proxy.command_inout(self._name, value)

                task = asyncio.create_task(_put())
                val = await asyncio.wait_for(task, timeout)
                self._last_reading = {
                    "value": val,
                    "timestamp": time.time(),
                    "alarm_severity": 0,
                }
            except asyncio.TimeoutError:
                raise TimeoutError(f"{self._name} command failed: Timeout")
            except DevFailed as e:
                raise RuntimeError(f"{self._name} device failure: {e.args[0].desc}")

        else:
            rid = self._proxy.command_inout_asynch(self._name, value)

            async def wait_for_reply(rd, to):
                reply_value = None
                start_time = time.time() if to else None
                while True:
                    try:
                        reply_value = self._proxy.command_inout_reply(rd)
                        self._last_reading = {
                            "value": reply_value,
                            "timestamp": time.time(),
                            "alarm_severity": 0,
                        }
                        break
                    except DevFailed as e:
                        if e.args[0].reason == "API_AsynReplyNotArrived":
                            await asyncio.sleep(A_BIT)
                            if to and time.time() - start_time > to:
                                raise TimeoutError(
                                    "Timeout while waiting for command reply"
                                )
                        else:
                            raise RuntimeError(
                                f"{self._name} device failure:" f" {e.args[0].desc}"
                            )

            return AsyncStatus(wait_for_reply(rid, timeout))

    @ensure_proper_executor
    async def get_config(self) -> CommandInfo:
        return await self._proxy.get_command_config(self._name)

    async def get_reading(self) -> Reading:
        reading = Reading(
            value=self._last_reading["value"],
            timestamp=self._last_reading["timestamp"],
            alarm_severity=self._last_reading["alarm_severity"],
        )
        return reading

    def set_polling(
        self,
        allow_polling: bool = False,
        polling_period: float = 0.5,
        abs_change=None,
        rel_change=0.1,
    ):
        pass


def get_dtype_extended(datatype):
    # DevState tango type does not have numpy equivalents
    dtype = get_dtype(datatype)
    if dtype == np.object_:
        if datatype.__args__[1].__args__[0] == DevState:
            dtype = CmdArgType.DevState
    return dtype


def get_trl_descriptor(
    datatype: Optional[Type],
    tango_resource: str,
    tr_configs: Dict[str, Union[AttributeInfoEx, CommandInfo]],
) -> dict:
    tr_dtype = {}
    for tr_name, config in tr_configs.items():
        if isinstance(config, AttributeInfoEx):
            _, dtype, descr = get_python_type(config.data_type)
            tr_dtype[tr_name] = config.data_format, dtype, descr
        elif isinstance(config, CommandInfo):
            if (
                config.in_type != CmdArgType.DevVoid
                and config.out_type != CmdArgType.DevVoid
                and config.in_type != config.out_type
            ):
                raise RuntimeError(
                    "Commands with different in and out dtypes are not supported"
                )
            array, dtype, descr = get_python_type(
                config.in_type
                if config.in_type != CmdArgType.DevVoid
                else config.out_type
            )
            tr_dtype[tr_name] = (
                AttrDataFormat.SPECTRUM if array else AttrDataFormat.SCALAR,
                dtype,
                descr,
            )
        else:
            raise RuntimeError(f"Unknown config type: {type(config)}")
    tr_format, tr_dtype, tr_dtype_desc = get_unique(tr_dtype, "typeids")

    # tango commands are limited in functionality:
    # they do not have info about shape and Enum labels
    trl_config = list(tr_configs.values())[0]
    max_x = trl_config.max_dim_x if hasattr(trl_config, "max_dim_x") else np.Inf
    max_y = trl_config.max_dim_y if hasattr(trl_config, "max_dim_y") else np.Inf
    is_attr = hasattr(trl_config, "enum_labels")
    trl_choices = list(trl_config.enum_labels) if is_attr else []

    if tr_format in [AttrDataFormat.SPECTRUM, AttrDataFormat.IMAGE]:
        # This is an array
        if datatype:
            # Check we wanted an array of this type
            dtype = get_dtype_extended(datatype)
            if not dtype:
                raise TypeError(
                    f"{tango_resource} has type [{tr_dtype}] not {datatype.__name__}"
                )
            if dtype != tr_dtype:
                raise TypeError(f"{tango_resource} has type [{tr_dtype}] not [{dtype}]")

        if tr_format == AttrDataFormat.SPECTRUM:
            return {"source": tango_resource, "dtype": "array", "shape": [max_x]}
        elif tr_format == AttrDataFormat.IMAGE:
            return {"source": tango_resource, "dtype": "array", "shape": [max_y, max_x]}

    else:
        if tr_dtype in (Enum, CmdArgType.DevState):
            if tr_dtype == CmdArgType.DevState:
                trl_choices = list(DevState.names.keys())

            if datatype:
                if not issubclass(datatype, (Enum, DevState)):
                    raise TypeError(
                        f"{tango_resource} has type Enum not {datatype.__name__}"
                    )
                if tr_dtype == Enum and is_attr:
                    choices = tuple(v.name for v in datatype)
                    if set(choices) != set(trl_choices):
                        raise TypeError(
                            f"{tango_resource} has choices {trl_choices} not {choices}"
                        )
            return {
                "source": tango_resource,
                "dtype": "string",
                "shape": [],
                "choices": trl_choices,
            }
        else:
            if datatype and not issubclass(tr_dtype, datatype):
                raise TypeError(
                    f"{tango_resource} has type {tr_dtype.__name__} "
                    f"not {datatype.__name__}"
                )
            return {"source": tango_resource, "dtype": tr_dtype_desc, "shape": []}


async def get_tango_trl(
    full_trl: str, device_proxy: Optional[DeviceProxy]
) -> TangoProxy:
    device_trl, trl_name = full_trl.rsplit("/", 1)
    trl_name = trl_name.lower()
    device_proxy = device_proxy or await DeviceProxy(device_trl)

    # all attributes can be always accessible with low register
    all_attrs = [attr_name.lower() for attr_name in device_proxy.get_attribute_list()]
    if trl_name in all_attrs:
        return AttributeProxy(device_proxy, trl_name)

    # all commands can be always accessible with low register
    all_cmds = [cmd_name.lower() for cmd_name in device_proxy.get_command_list()]
    if trl_name in all_cmds:
        return CommandProxy(device_proxy, trl_name)

    # If version is below tango 9, then pipes are not supported
    if device_proxy.info().server_version >= 9:
        # all pipes can be always accessible with low register
        all_pipes = [pipe_name.lower() for pipe_name in device_proxy.get_pipe_list()]
        if trl_name in all_pipes:
            raise NotImplementedError("Pipes are not supported")

    raise RuntimeError(f"{trl_name} cannot be found in {device_proxy.name()}")


class TangoSignalBackend(SignalBackend[T]):
    def __init__(
        self,
        datatype: Optional[Type[T]],
        read_trl: str,
        write_trl: str,
        device_proxy: Optional[DeviceProxy] = None,
    ):
        self.datatype = datatype
        self.read_trl = read_trl
        self.write_trl = write_trl
        self.proxies: Dict[str, TangoProxy] = {
            read_trl: device_proxy,
            write_trl: device_proxy,
        }
        self.trl_configs: Dict[str, AttributeInfoEx] = {}
        self.descriptor: Descriptor = {}  # type: ignore
        self._polling = (False, 0.1, None, 0.1)
        self.support_events = True
        self.status = None

    def source(self, name: str) -> str:
        return self.read_trl

    async def _connect_and_store_config(self, trl):
        try:
            self.proxies[trl] = await get_tango_trl(trl, self.proxies[trl])
            await self.proxies[trl].connect()
            self.trl_configs[trl] = await self.proxies[trl].get_config()
            self.proxies[trl].support_events = self.support_events
        except CancelledError:
            raise NotConnected(f"Could not connect to {trl}")

    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        if self.read_trl != self.write_trl:
            # Different, need to connect both
            await wait_for_connection(
                read_trl=self._connect_and_store_config(self.read_trl),
                write_trl=self._connect_and_store_config(self.write_trl),
            )
        else:
            # The same, so only need to connect one
            await self._connect_and_store_config(self.read_trl)
        self.proxies[self.read_trl].set_polling(*self._polling)
        self.descriptor = get_trl_descriptor(
            self.datatype, self.read_trl, self.trl_configs
        )

    async def put(self, value: Optional[T], wait=True, timeout=None):
        self.status = None
        put_status = await self.proxies[self.write_trl].put(value, wait, timeout)
        self.status = put_status

    async def get_datakey(self, source: str) -> DataKey:
        return self.descriptor

    async def get_reading(self) -> Reading:
        return await self.proxies[self.read_trl].get_reading()

    async def get_value(self) -> T:
        return await self.proxies[self.write_trl].get()

    async def get_setpoint(self) -> T:
        return await self.proxies[self.write_trl].get_w_value()

    def set_callback(self, callback: Optional[ReadingValueCallback]) -> None:
        if self.support_events is False and self._polling[0] is False:
            raise RuntimeError(
                f"Cannot set event for {self.read_trl}. "
                "Cannot set a callback on an attribute that does not support events and"
                " for which polling is disabled."
            )

        if callback:
            try:
                assert not self.proxies[self.read_trl].has_subscription()
                self.proxies[self.read_trl].subscribe_callback(callback)
            except AssertionError:
                raise RuntimeError("Cannot set a callback when one is already set")
            except RuntimeError as exc:
                raise RuntimeError(f"Cannot set callback for {self.read_trl}. {exc}")

        else:
            self.proxies[self.read_trl].unsubscribe_callback()

    def set_polling(
        self,
        allow_polling: bool = True,
        polling_period: float = 0.1,
        abs_change=None,
        rel_change=0.1,
    ):
        self._polling = (allow_polling, polling_period, abs_change, rel_change)

    def allow_events(self, allow: Optional[bool] = True):
        self.support_events = allow
