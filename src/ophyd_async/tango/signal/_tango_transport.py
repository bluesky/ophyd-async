import asyncio
import functools
import time
from abc import abstractmethod
from asyncio import CancelledError
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any, TypeVar, cast

import numpy as np
from bluesky.protocols import Descriptor, Reading

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
    DevFailed,  # type: ignore
    DeviceProxy,
    DevState,
    EventType,
)
from tango.asyncio import DeviceProxy as AsyncDeviceProxy
from tango.asyncio_executor import (
    AsyncioExecutor,
    get_global_executor,
    set_global_executor,
)
from tango.utils import is_array, is_binary, is_bool, is_float, is_int, is_str

# time constant to wait for timeout
A_BIT = 1e-5

R = TypeVar("R")


def ensure_proper_executor(
    func: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> R:
        current_executor: AsyncioExecutor = get_global_executor()  # type: ignore
        if not current_executor.in_executor_context():  # type: ignore
            set_global_executor(AsyncioExecutor())
        return await func(self, *args, **kwargs)

    return cast(Callable[..., Coroutine[Any, Any, R]], wrapper)


def get_python_type(tango_type: CmdArgType) -> tuple[bool, object, str]:
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
    support_events: bool = True
    _proxy: DeviceProxy
    _name: str

    def __init__(self, device_proxy: DeviceProxy, name: str):
        self._proxy = device_proxy
        self._name = name

    async def connect(self) -> None:
        """perform actions after proxy is connected, e.g. checks if signal
        can be subscribed"""

    @abstractmethod
    async def get(self) -> object:
        """Get value from TRL"""

    @abstractmethod
    async def get_w_value(self) -> object:
        """Get last written value from TRL"""

    @abstractmethod
    async def put(
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        """Put value to TRL"""

    @abstractmethod
    async def get_config(self) -> AttributeInfoEx | CommandInfo:
        """Get TRL config async"""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """Get reading from TRL"""

    @abstractmethod
    def has_subscription(self) -> bool:
        """indicates, that this trl already subscribed"""

    @abstractmethod
    def subscribe_callback(self, callback: ReadingValueCallback | None):
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
    _callback: ReadingValueCallback | None = None
    _eid: int | None = None
    _poll_task: asyncio.Task | None = None
    _abs_change: float | None = None
    _rel_change: float | None = 0.1
    _polling_period: float = 0.1
    _allow_polling: bool = False
    exception: BaseException | None = None
    _last_reading: Reading = Reading(value=None, timestamp=0, alarm_severity=0)

    async def connect(self) -> None:
        try:
            # I have to typehint proxy as tango.DeviceProxy because
            # tango.asyncio.DeviceProxy cannot be used as a typehint.
            # This means pyright will not be able to see that
            # subscribe_event is awaitable.
            eid = await self._proxy.subscribe_event(  # type: ignore
                self._name, EventType.CHANGE_EVENT, self._event_processor
            )
            await self._proxy.unsubscribe_event(eid)
            self.support_events = True
        except Exception:
            pass

    @ensure_proper_executor
    async def get(self) -> Coroutine[Any, Any, object]:
        attr = await self._proxy.read_attribute(self._name)
        return attr.value

    @ensure_proper_executor
    async def get_w_value(self) -> object:
        attr = await self._proxy.read_attribute(self._name)
        return attr.w_value

    @ensure_proper_executor
    async def put(
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        if wait:
            try:

                async def _write():
                    return await self._proxy.write_attribute(self._name, value)

                task = asyncio.create_task(_write())
                await asyncio.wait_for(task, timeout)
            except asyncio.TimeoutError as te:
                raise TimeoutError(f"{self._name} attr put failed: Timeout") from te
            except DevFailed as de:
                raise RuntimeError(
                    f"{self._name} device" f" failure: {de.args[0].desc}"
                ) from de

        else:
            rid = await self._proxy.write_attribute_asynch(self._name, value)

            async def wait_for_reply(rd: int, to: float | None):
                start_time = time.time()
                while True:
                    try:
                        # I have to typehint proxy as tango.DeviceProxy because
                        # tango.asyncio.DeviceProxy cannot be used as a typehint.
                        # This means pyright will not be able to see that
                        # write_attribute_reply is awaitable.
                        await self._proxy.write_attribute_reply(rd)  # type: ignore
                        break
                    except DevFailed as exc:
                        if exc.args[0].reason == "API_AsynReplyNotArrived":
                            await asyncio.sleep(A_BIT)
                            if to and (time.time() - start_time > to):
                                raise TimeoutError(
                                    f"{self._name} attr put failed:" f" Timeout"
                                ) from exc
                        else:
                            raise RuntimeError(
                                f"{self._name} device failure:" f" {exc.args[0].desc}"
                            ) from exc

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

    def subscribe_callback(self, callback: ReadingValueCallback | None):
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
                        except RuntimeError as exc:
                            self.exception = exc
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
            reading = Reading(
                value=value,
                timestamp=event.get_date().totime(),
                alarm_severity=event.attr_value.quality,
            )
            if self._callback is not None:
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
            raise RuntimeError(f"Could not poll the attribute: {e}") from e

        try:
            # If the value is a number, we can check for changes
            if isinstance(last_reading["value"], int | float):
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
            raise RuntimeError(f"Could not poll the attribute: {e}") from e

    def set_polling(
        self,
        allow_polling: bool = False,
        polling_period: float = 0.5,
        abs_change: float | None = None,
        rel_change: float | None = 0.1,
    ):
        """
        Set the polling parameters.
        """
        self._allow_polling = allow_polling
        self._polling_period = polling_period
        self._abs_change = abs_change
        self._rel_change = rel_change


class CommandProxy(TangoProxy):
    _last_reading: Reading = Reading(value=None, timestamp=0, alarm_severity=0)

    def subscribe_callback(self, callback: ReadingValueCallback | None) -> None:
        raise NotImplementedError("Cannot subscribe to commands")

    def unsubscribe_callback(self) -> None:
        raise NotImplementedError("Cannot unsubscribe from commands")

    async def get(self) -> object:
        return self._last_reading["value"]

    async def get_w_value(self) -> object:
        return self._last_reading["value"]

    async def connect(self) -> None:
        pass

    @ensure_proper_executor
    async def put(
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        if wait:
            try:

                async def _put():
                    return await self._proxy.command_inout(self._name, value)

                task = asyncio.create_task(_put())
                val = await asyncio.wait_for(task, timeout)
                self._last_reading = Reading(
                    value=val, timestamp=time.time(), alarm_severity=0
                )
            except asyncio.TimeoutError as te:
                raise TimeoutError(f"{self._name} command failed: Timeout") from te
            except DevFailed as de:
                raise RuntimeError(
                    f"{self._name} device" f" failure: {de.args[0].desc}"
                ) from de

        else:
            rid = self._proxy.command_inout_asynch(self._name, value)

            async def wait_for_reply(rd: int, to: float | None):
                start_time = time.time()
                while True:
                    try:
                        reply_value = self._proxy.command_inout_reply(rd)
                        self._last_reading = Reading(
                            value=reply_value, timestamp=time.time(), alarm_severity=0
                        )
                        break
                    except DevFailed as de_exc:
                        if de_exc.args[0].reason == "API_AsynReplyNotArrived":
                            await asyncio.sleep(A_BIT)
                            if to and time.time() - start_time > to:
                                raise TimeoutError(
                                    "Timeout while waiting for command reply"
                                ) from de_exc
                        else:
                            raise RuntimeError(
                                f"{self._name} device failure:"
                                f" {de_exc.args[0].desc}"
                            ) from de_exc

            return AsyncStatus(wait_for_reply(rid, timeout))

    @ensure_proper_executor
    async def get_config(self) -> CommandInfo:
        return await self._proxy.get_command_config(self._name)

    async def get_reading(self) -> Reading:
        reading = Reading(
            value=self._last_reading["value"],
            timestamp=self._last_reading["timestamp"],
            alarm_severity=self._last_reading.get("alarm_severity", 0),
        )
        return reading

    def set_polling(
        self,
        allow_polling: bool = False,
        polling_period: float = 0.5,
        abs_change: float | None = None,
        rel_change: float | None = 0.1,
    ):
        pass


def get_dtype_extended(datatype) -> object | None:
    # DevState tango type does not have numpy equivalents
    dtype = get_dtype(datatype)
    if dtype == np.object_:
        if datatype.__args__[1].__args__[0] == DevState:
            dtype = CmdArgType.DevState
    return dtype


def get_trl_descriptor(
    datatype: type | None,
    tango_resource: str,
    tr_configs: dict[str, AttributeInfoEx | CommandInfo],
) -> Descriptor:
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
    max_x: int = (
        trl_config.max_dim_x
        if hasattr(trl_config, "max_dim_x")
        else np.iinfo(np.int32).max
    )
    max_y: int = (
        trl_config.max_dim_y
        if hasattr(trl_config, "max_dim_y")
        else np.iinfo(np.int32).max
    )
    # is_attr = hasattr(trl_config, "enum_labels")
    # trl_choices = list(trl_config.enum_labels) if is_attr else []

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
            return Descriptor(source=tango_resource, dtype="array", shape=[max_x])
        elif tr_format == AttrDataFormat.IMAGE:
            return Descriptor(
                source=tango_resource, dtype="array", shape=[max_y, max_x]
            )

    else:
        if tr_dtype in (Enum, CmdArgType.DevState):
            # if tr_dtype == CmdArgType.DevState:
            #     trl_choices = list(DevState.names.keys())

            if datatype:
                if not issubclass(datatype, Enum | DevState):
                    raise TypeError(
                        f"{tango_resource} has type Enum not {datatype.__name__}"
                    )
                # if tr_dtype == Enum and is_attr:
                #     if isinstance(datatype, DevState):
                #         choices = tuple(v.name for v in datatype)
                #         if set(choices) != set(trl_choices):
                #             raise TypeError(
                #                 f"{tango_resource} has choices {trl_choices} "
                #                 f"not {choices}"
                #             )
            return Descriptor(source=tango_resource, dtype="string", shape=[])
        else:
            if datatype and not issubclass(tr_dtype, datatype):
                raise TypeError(
                    f"{tango_resource} has type {tr_dtype.__name__} "
                    f"not {datatype.__name__}"
                )
            return Descriptor(source=tango_resource, dtype=tr_dtype_desc, shape=[])

    raise RuntimeError(f"Error getting descriptor for {tango_resource}")


async def get_tango_trl(
    full_trl: str, device_proxy: DeviceProxy | TangoProxy | None
) -> TangoProxy:
    if isinstance(device_proxy, TangoProxy):
        return device_proxy
    device_trl, trl_name = full_trl.rsplit("/", 1)
    trl_name = trl_name.lower()
    if device_proxy is None:
        device_proxy = await AsyncDeviceProxy(device_trl)

    # all attributes can be always accessible with low register
    if isinstance(device_proxy, DeviceProxy):
        all_attrs = [
            attr_name.lower() for attr_name in device_proxy.get_attribute_list()
        ]
    else:
        raise TypeError(
            f"device_proxy must be an instance of DeviceProxy for {full_trl}"
        )
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
        datatype: type[T] | None,
        read_trl: str = "",
        write_trl: str = "",
        device_proxy: DeviceProxy | None = None,
    ):
        self.device_proxy = device_proxy
        self.datatype = datatype
        self.read_trl = read_trl
        self.write_trl = write_trl
        self.proxies: dict[str, TangoProxy | DeviceProxy | None] = {
            read_trl: self.device_proxy,
            write_trl: self.device_proxy,
        }
        self.trl_configs: dict[str, AttributeInfoEx] = {}
        self.descriptor: Descriptor = {}  # type: ignore
        self._polling: tuple[bool, float, float | None, float | None] = (
            False,
            0.1,
            None,
            0.1,
        )
        self.support_events: bool = True
        self.status: AsyncStatus | None = None

    @classmethod
    def datatype_allowed(cls, dtype: Any) -> bool:
        return dtype in (int, float, str, bool, np.ndarray, Enum, DevState)

    def set_trl(self, read_trl: str = "", write_trl: str = ""):
        self.read_trl = read_trl
        self.write_trl = write_trl if write_trl else read_trl
        self.proxies = {
            read_trl: self.device_proxy,
            write_trl: self.device_proxy,
        }

    def source(self, name: str) -> str:
        return self.read_trl

    async def _connect_and_store_config(self, trl: str) -> None:
        if not trl:
            raise RuntimeError(f"trl not set for {self}")
        try:
            self.proxies[trl] = await get_tango_trl(trl, self.proxies[trl])
            if self.proxies[trl] is None:
                raise NotConnected(f"Not connected to {trl}")
            # Pyright does not believe that self.proxies[trl] is not None despite
            # the check above
            await self.proxies[trl].connect()  # type: ignore
            self.trl_configs[trl] = await self.proxies[trl].get_config()  # type: ignore
            self.proxies[trl].support_events = self.support_events  # type: ignore
        except CancelledError as ce:
            raise NotConnected(f"Could not connect to {trl}") from ce

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not self.read_trl:
            raise RuntimeError(f"trl not set for {self}")
        if self.read_trl != self.write_trl:
            # Different, need to connect both
            await wait_for_connection(
                read_trl=self._connect_and_store_config(self.read_trl),
                write_trl=self._connect_and_store_config(self.write_trl),
            )
        else:
            # The same, so only need to connect one
            await self._connect_and_store_config(self.read_trl)
        self.proxies[self.read_trl].set_polling(*self._polling)  # type: ignore
        self.descriptor = get_trl_descriptor(
            self.datatype, self.read_trl, self.trl_configs
        )

    async def put(self, value: T | None, wait=True, timeout=None) -> None:
        if self.proxies[self.write_trl] is None:
            raise NotConnected(f"Not connected to {self.write_trl}")
        self.status = None
        put_status = await self.proxies[self.write_trl].put(value, wait, timeout)  # type: ignore
        self.status = put_status

    async def get_datakey(self, source: str) -> Descriptor:
        return self.descriptor

    async def get_reading(self) -> Reading:
        if self.proxies[self.read_trl] is None:
            raise NotConnected(f"Not connected to {self.read_trl}")
        return await self.proxies[self.read_trl].get_reading()  # type: ignore

    async def get_value(self) -> T:
        if self.proxies[self.read_trl] is None:
            raise NotConnected(f"Not connected to {self.read_trl}")
        proxy = self.proxies[self.read_trl]
        if proxy is None:
            raise NotConnected(f"Not connected to {self.read_trl}")
        return cast(T, await proxy.get())

    async def get_setpoint(self) -> T:
        if self.proxies[self.write_trl] is None:
            raise NotConnected(f"Not connected to {self.write_trl}")
        proxy = self.proxies[self.write_trl]
        if proxy is None:
            raise NotConnected(f"Not connected to {self.write_trl}")
        return cast(T, await proxy.get_w_value())

    def set_callback(self, callback: ReadingValueCallback | None) -> None:
        if self.proxies[self.read_trl] is None:
            raise NotConnected(f"Not connected to {self.read_trl}")
        if self.support_events is False and self._polling[0] is False:
            raise RuntimeError(
                f"Cannot set event for {self.read_trl}. "
                "Cannot set a callback on an attribute that does not support events and"
                " for which polling is disabled."
            )

        if callback:
            try:
                assert not self.proxies[self.read_trl].has_subscription()  # type: ignore
                self.proxies[self.read_trl].subscribe_callback(callback)  # type: ignore
            except AssertionError as ae:
                raise RuntimeError(
                    "Cannot set a callback when one" " is already set"
                ) from ae
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Cannot set callback" f" for {self.read_trl}. {exc}"
                ) from exc

        else:
            self.proxies[self.read_trl].unsubscribe_callback()  # type: ignore

    def set_polling(
        self,
        allow_polling: bool = True,
        polling_period: float = 0.1,
        abs_change: float | None = None,
        rel_change: float | None = 0.1,
    ):
        self._polling = (allow_polling, polling_period, abs_change, rel_change)

    def allow_events(self, allow: bool = True):
        self.support_events = allow
