import asyncio
import functools
import logging
import time
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Sequence
from typing import (
    Any,
    ParamSpec,
    TypeVar,
    cast,
    get_args,
    get_origin,
)

import numpy as np
import numpy.typing as npt
from bluesky.protocols import Reading
from event_model import DataKey, Limits, LimitsRange
from event_model.documents.event_descriptor import RdsRange
from tango import (
    AttrDataFormat,
    AttributeInfo,
    AttributeInfoEx,
    CmdArgType,
    CommandInfo,
    DevFailed,  # type: ignore
    DeviceProxy,
    DevState,
    EventType,
    GreenMode,
)
from tango.asyncio import DeviceProxy as AsyncDeviceProxy
from tango.asyncio_executor import (
    AsyncioExecutor,
    get_global_executor,
    set_global_executor,
)
from tango.utils import is_binary, is_bool, is_float, is_int, is_str

from ophyd_async.core import (
    Array1D,
    AsyncStatus,
    Callback,
    NotConnectedError,
    SignalBackend,
    SignalDatatypeT,
    SignalMetadata,
    StrictEnum,
    Table,
    get_dtype,
    make_datakey,
    wait_for_connection,
)
from ophyd_async.tango.testing import TestConfig

from ._converters import (
    TangoConverter,
    TangoDevStateArrayConverter,
    TangoDevStateConverter,
    TangoEnumArrayConverter,
    TangoEnumConverter,
)
from ._utils import DevStateEnum, get_device_trl_and_attr, try_to_cast_as_float

logger = logging.getLogger("ophyd_async")

# time constant to wait for timeout
A_BIT = 1e-5

P = ParamSpec("P")
R = TypeVar("R")


def ensure_proper_executor(
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Ensure decorated method has a proper asyncio executor."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        current_executor: AsyncioExecutor = get_global_executor()  # type: ignore
        if not current_executor.in_executor_context():  # type: ignore
            set_global_executor(AsyncioExecutor())
        return await func(*args, **kwargs)

    return wrapper


class TangoLongStringTable(Table):
    long: Array1D[np.int32]
    string: Sequence[str]


class TangoDoubleStringTable(Table):
    double: Array1D[np.float64]
    string: Sequence[str]


def get_python_type(config: AttributeInfoEx | CommandInfo | TestConfig) -> object:
    """For converting between recieved tango types and python primatives."""
    tango_type = None
    tango_format = None
    if isinstance(config, AttributeInfoEx | AttributeInfo):
        tango_type = config.data_type
        tango_format = config.data_format
    elif isinstance(config, CommandInfo):
        read_character = get_command_character(config)
        if read_character == CommandProxyReadCharacter.READ:
            tango_type = config.out_type
        else:
            tango_type = config.in_type
    elif isinstance(config, TestConfig):
        tango_type = config.data_type
        tango_format = config.data_format
    else:
        raise TypeError("Unrecognized Tango resource configuration")
    if tango_format not in [
        AttrDataFormat.SCALAR,
        AttrDataFormat.SPECTRUM,
        AttrDataFormat.IMAGE,
        None,
    ]:
        raise TypeError("Unknown TangoFormat")

    if tango_type is CmdArgType.DevVarLongStringArray:
        return TangoLongStringTable
    if tango_type is CmdArgType.DevVarDoubleStringArray:
        return TangoDoubleStringTable

    def _get_type(cls: type) -> object:
        if tango_format == AttrDataFormat.SCALAR:
            return cls
        elif tango_format == AttrDataFormat.SPECTRUM:
            if cls is str or issubclass(cls, StrictEnum):
                return Sequence[cls]
            return Array1D[cls]
        elif tango_format == AttrDataFormat.IMAGE:
            if cls is str or issubclass(cls, StrictEnum):
                return Sequence[Sequence[str]]
            return npt.NDArray[cls]
        else:
            return cls

    if is_int(tango_type, True):
        return _get_type(int)
    elif is_float(tango_type, True):
        return _get_type(float)
    elif is_bool(tango_type, True):
        return _get_type(bool)
    elif is_str(tango_type, True):
        return _get_type(str)
    elif is_binary(tango_type, True):
        return _get_type(str)
    elif tango_type == CmdArgType.DevEnum:
        if hasattr(config, "enum_labels"):
            enum_dict = {label: str(label) for label in config.enum_labels}
            return _get_type(StrictEnum("TangoEnum", enum_dict))
        else:
            return _get_type(int)
    elif tango_type == CmdArgType.DevState:
        return _get_type(DevStateEnum)
    elif tango_type == CmdArgType.DevUChar:
        return _get_type(int)
    elif tango_type == CmdArgType.DevVoid:
        return None
    else:
        raise TypeError(f"Unknown TangoType: {tango_type}")


class TangoProxy:
    support_events: bool = True
    _proxy: DeviceProxy
    _name: str
    _converter: TangoConverter = TangoConverter()

    def __init__(self, device_proxy: DeviceProxy, name: str):
        self._proxy = device_proxy
        self._name = name

    async def connect(self) -> None:
        """Perform actions after proxy is connected.

        e.g. check if signal can be subscribed.
        """

    @abstractmethod
    async def get(self) -> object:
        """Get value from TRL."""

    @abstractmethod
    async def get_w_value(self) -> object:
        """Get last written value from TRL."""

    @abstractmethod
    async def put(
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        """Put value to TRL."""

    @abstractmethod
    async def get_config(self) -> AttributeInfoEx | CommandInfo:
        """Get TRL config async."""

    @abstractmethod
    async def get_reading(self) -> Reading:
        """Get reading from TRL."""

    @abstractmethod
    def has_subscription(self) -> bool:
        """Indicate that this trl already subscribed."""

    @abstractmethod
    def subscribe_callback(self, callback: Callback | None):
        """Subscribe tango CHANGE event to callback."""

    @abstractmethod
    def unsubscribe_callback(self):
        """Delete CHANGE event subscription."""

    @abstractmethod
    def set_polling(
        self,
        allow_polling: bool = True,
        polling_period: float = 0.1,
        abs_change=None,
        rel_change=None,
    ):
        """Set polling parameters."""

    def set_converter(self, converter: "TangoConverter"):
        self._converter = converter


class AttributeProxy(TangoProxy):
    """Used by the tango transport."""

    _callback: Callback | None = None
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
    async def get(self) -> object:  # type: ignore
        attr = await self._proxy.read_attribute(self._name)
        return self._converter.value(attr.value)

    @ensure_proper_executor
    async def get_w_value(self) -> object:  # type: ignore
        attr = await self._proxy.read_attribute(self._name)
        return self._converter.value(attr.w_value)

    @ensure_proper_executor
    async def put(  # type: ignore
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        if wait is False:
            raise RuntimeWarning(
                "wait=False is not supported in Tango."
                "Simply don't await the status object."
            )
        # TODO: remove the timeout from this as it is handled at the signal level
        value = self._converter.write_value(value)
        try:

            async def _write():
                return await self._proxy.write_attribute(self._name, value)

            task = asyncio.create_task(_write())
            await asyncio.wait_for(task, timeout)
        except TimeoutError as te:
            raise TimeoutError(f"{self._name} attr put failed: Timeout") from te
        except DevFailed as de:
            raise RuntimeError(
                f"{self._name} device failure: {de.args[0].desc}"
            ) from de

    @ensure_proper_executor
    async def get_config(self) -> AttributeInfoEx:  # type: ignore
        return await self._proxy.get_attribute_config(self._name)

    @ensure_proper_executor
    async def get_reading(self) -> Reading:  # type: ignore
        attr = await self._proxy.read_attribute(self._name)
        reading = Reading(
            value=self._converter.value(attr.value),
            timestamp=attr.time.totime(),
            alarm_severity=attr.quality,
        )
        self._last_reading = reading
        return reading

    def has_subscription(self) -> bool:
        return bool(self._callback)

    @ensure_proper_executor
    async def _subscribe_to_event(self):
        if not self._eid:
            self._eid = await self._proxy.subscribe_event(
                self._name,
                EventType.CHANGE_EVENT,
                self._event_processor,
                stateless=True,
                green_mode=GreenMode.Asyncio,
            )

    def subscribe_callback(self, callback: Callback | None):
        # If the attribute supports events, then we can subscribe to them
        # If the callback is not a callable, then we raise an error
        if callback is not None and not callable(callback):
            raise RuntimeError("Callback must be a callable")

        self._callback = callback
        if self.support_events:
            asyncio.create_task(self._subscribe_to_event())
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
            try:
                self._proxy.unsubscribe_event(self._eid, green_mode=False)
            except Exception as exc:
                logger.warning(f"Could not unsubscribe from event: {exc}")
            finally:
                self._eid = None
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
            if self._callback is not None:
                # Call the callback with the last reading
                try:
                    self._callback(self._last_reading)
                except TypeError:
                    pass
        self._callback = None

    @ensure_proper_executor
    async def _event_processor(self, event):
        if not event.err:
            reading = Reading(
                value=self._converter.value(event.attr_value.value),
                timestamp=event.get_date().totime(),
                alarm_severity=event.attr_value.quality,
            )
            if self._callback is not None:
                self._callback(reading)

    async def poll(self):
        """Poll the attribute and call the callback if the value has changed.

        Only callback if value has changed by more than the absolute or relative
        change. This function is used when an attribute that does not support
        events is cached or a callback is passed to it.
        """
        try:
            last_reading = await self.get_reading()
            flag = 0
            # Initial reading
            if self._callback is not None:
                self._callback(last_reading)
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
                            self._callback(reading)
                            flag = 0

                    elif (
                        self._rel_change is not None
                        and diff >= self._rel_change * abs(last_reading["value"])
                    ):
                        if self._callback is not None:
                            self._callback(reading)
                            flag = 0

                    else:
                        flag = (flag + 1) % 4
                        if flag == 0 and self._callback is not None:
                            self._callback(reading)

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
                                    self._callback(reading)
                                else:
                                    break
                        else:
                            if reading["value"] != last_reading["value"]:
                                if self._callback is not None:
                                    self._callback(reading)
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
        """Set the polling parameters."""
        self._allow_polling = allow_polling
        self._polling_period = polling_period
        self._abs_change = abs_change
        self._rel_change = rel_change


class CommandProxyReadCharacter(StrictEnum):
    """Enum to carry the read/write character of the CommandProxy."""

    READ = "READ"
    WRITE = "WRITE"
    READ_WRITE = "READ_WRITE"
    EXECUTE = "EXECUTE"


def get_command_character(config: CommandInfo) -> CommandProxyReadCharacter:
    """Return the command character for the given command config."""
    in_type = config.in_type
    out_type = config.out_type
    if in_type == CmdArgType.DevVoid and out_type != CmdArgType.DevVoid:
        read_character = CommandProxyReadCharacter.READ
    elif in_type != CmdArgType.DevVoid and out_type == CmdArgType.DevVoid:
        read_character = CommandProxyReadCharacter.WRITE
    elif in_type == CmdArgType.DevVoid and out_type == CmdArgType.DevVoid:
        read_character = CommandProxyReadCharacter.EXECUTE
    else:
        read_character = CommandProxyReadCharacter.READ_WRITE
    return read_character


class CommandProxy(TangoProxy):
    """Tango proxy for commands."""

    _last_reading: Reading
    _last_w_value: Any
    _config: CommandInfo
    _read_character: CommandProxyReadCharacter
    device_proxy: DeviceProxy
    name: str

    def __init__(self, device_proxy: DeviceProxy, name: str):
        super().__init__(device_proxy, name)
        self._last_reading = Reading(value=None, timestamp=0, alarm_severity=0)
        self.device_proxy = device_proxy
        self.name = name
        self._last_w_value = None

    def subscribe_callback(self, callback: Callback | None) -> None:
        raise NotImplementedError("Cannot subscribe to commands")

    def unsubscribe_callback(self) -> None:
        raise NotImplementedError("Cannot unsubscribe from commands")

    async def get(self) -> object:
        if self._read_character == CommandProxyReadCharacter.READ_WRITE:
            return self._last_reading["value"]
        elif self._read_character == CommandProxyReadCharacter.READ:
            await self.put(value=None, wait=True, timeout=None)
            return self._last_reading["value"]

    async def get_w_value(self) -> object:
        return self._last_w_value

    async def connect(self) -> None:
        self._config = await self.device_proxy.get_command_config(self.name)
        self._read_character = get_command_character(self._config)

    @ensure_proper_executor
    async def put(  # type: ignore
        self, value: object | None, wait: bool = True, timeout: float | None = None
    ) -> AsyncStatus | None:
        if wait is False:
            raise RuntimeError(
                "wait=False is not supported in Tango."
                " Simply don't await the status object."
            )
        value = self._converter.write_value(value)
        try:

            async def _put():
                return await self._proxy.command_inout(self._name, value)

            task = asyncio.create_task(_put())
            val = await asyncio.wait_for(task, timeout)
            self._last_w_value = value
            self._last_reading = Reading(
                value=self._converter.value(val),
                timestamp=time.time(),
                alarm_severity=0,
            )
        except TimeoutError as te:
            raise TimeoutError(f"{self._name} command failed: Timeout") from te
        except DevFailed as de:
            raise RuntimeError(
                f"{self._name} device failure: {de.args[0].desc}"
            ) from de

    @ensure_proper_executor
    async def get_config(self) -> CommandInfo:  # type: ignore
        return await self._proxy.get_command_config(self._name)

    async def get_reading(self) -> Reading:
        if self._read_character == CommandProxyReadCharacter.READ:
            await self.put(value=None, wait=True, timeout=None)
            return self._last_reading
        else:
            return self._last_reading

    def set_polling(
        self,
        allow_polling: bool = False,
        polling_period: float = 0.5,
        abs_change: float | None = None,
        rel_change: float | None = 0.1,
    ):
        pass


def get_dtype_extended(datatype) -> object | None:
    """For converting tango types to numpy datatype formats."""
    # DevState tango type does not have numpy equivalents
    dtype = get_dtype(datatype)
    if dtype == np.object_:
        if datatype.__args__[1].__args__[0] in [DevStateEnum, DevState]:
            dtype = CmdArgType.DevState
    return dtype


def get_source_metadata(
    tango_resource: str,
    tr_configs: dict[str, AttributeInfoEx],
) -> SignalMetadata:
    metadata = {}
    for _, config in tr_configs.items():
        if isinstance(config, AttributeInfoEx):
            alarm_info = config.alarms
            _limits = Limits(
                control=LimitsRange(
                    low=try_to_cast_as_float(config.min_value),
                    high=try_to_cast_as_float(config.max_value),
                ),
                warning=LimitsRange(
                    low=try_to_cast_as_float(alarm_info.min_warning),
                    high=try_to_cast_as_float(alarm_info.max_warning),
                ),
                alarm=LimitsRange(
                    low=try_to_cast_as_float(alarm_info.min_alarm),
                    high=try_to_cast_as_float(alarm_info.max_alarm),
                ),
            )

            delta_t, delta_val = map(
                try_to_cast_as_float, (alarm_info.delta_t, alarm_info.delta_val)
            )
            if isinstance(delta_t, float) and isinstance(delta_val, float):
                limits_rds = RdsRange(
                    time_difference=delta_t,
                    value_difference=delta_val,
                )
                _limits["rds"] = limits_rds
            # if only one of the two is set
            elif isinstance(delta_t, float) ^ isinstance(delta_val, float):
                logger.warning(
                    f"Both delta_t and delta_val should be set for {tango_resource} "
                    f"but only one is set. "
                    f"delta_t: {alarm_info.delta_t}, delta_val: {alarm_info.delta_val}"
                )

            _choices = list(config.enum_labels) if config.enum_labels else []

            tr_dtype = get_python_type(config)

            if tr_dtype == CmdArgType.DevState:
                _choices = list(DevState.names.keys())

            _precision = None
            if config.format:
                try:
                    _precision = int(config.format.split(".")[1].split("f")[0])
                except (ValueError, IndexError) as e:
                    # If parsing config.format fails, _precision remains None.
                    logger.warning(
                        "Failed to parse precision from config.format: %s. Error: %s",
                        config.format,
                        e,
                    )
            no_limits = Limits(
                control=LimitsRange(high=None, low=None),
                warning=LimitsRange(high=None, low=None),
                alarm=LimitsRange(high=None, low=None),
            )
            if _limits:
                if _limits != no_limits:
                    metadata["limits"] = _limits
            if _choices:
                metadata["choices"] = _choices
            if _precision:
                metadata["precision"] = _precision
            if config.unit:
                metadata["units"] = config.unit
    return SignalMetadata(**metadata)


async def get_tango_trl(
    full_trl: str, device_proxy: DeviceProxy | TangoProxy | None, timeout: float
) -> TangoProxy:
    """Get the tango resource locator."""
    if isinstance(device_proxy, TangoProxy):
        return device_proxy
    device_trl, trl_name = get_device_trl_and_attr(full_trl)
    trl_name = trl_name.lower()
    if device_proxy is None:
        device_proxy = await AsyncDeviceProxy(device_trl, timeout=timeout)
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

    raise RuntimeError(f"{trl_name} cannot be found in {device_proxy.name()}")


def make_converter(info: AttributeInfoEx | CommandInfo, datatype) -> TangoConverter:
    if isinstance(info, AttributeInfoEx):
        match info.data_type:
            case CmdArgType.DevEnum:
                if datatype and issubclass(datatype, StrictEnum):
                    labels = [e.value for e in datatype]
                else:  # get from enum_labels metadata
                    labels = list(info.enum_labels)
                if info.data_format == AttrDataFormat.SCALAR:
                    return TangoEnumConverter(labels)
                elif info.data_format in [
                    AttrDataFormat.SPECTRUM,
                    AttrDataFormat.IMAGE,
                ]:
                    return TangoEnumArrayConverter(labels)
            case CmdArgType.DevState:
                if info.data_format == AttrDataFormat.SCALAR:
                    return TangoDevStateConverter()
                elif info.data_format in [
                    AttrDataFormat.SPECTRUM,
                    AttrDataFormat.IMAGE,
                ]:
                    return TangoDevStateArrayConverter()
    else:  # command info
        match info.in_type:
            case CmdArgType.DevState:
                return TangoDevStateConverter()
            case CmdArgType.DevEnum:
                if datatype and issubclass(datatype, StrictEnum):
                    labels = [e.value for e in datatype]
                    return TangoEnumConverter(labels)
                else:
                    logger.warning(
                        "No override enum class provided for Tango enum command"
                    )
    # default case return trivial converter
    return TangoConverter()


class TangoSignalBackend(SignalBackend[SignalDatatypeT]):
    """Tango backend to connect signals over tango."""

    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        read_trl: str = "",
        write_trl: str = "",
        device_proxy: DeviceProxy | None = None,
    ):
        self.device_proxy = device_proxy
        self.read_trl = read_trl
        self.write_trl = write_trl
        self.proxies: dict[str, TangoProxy | DeviceProxy | None] = {
            read_trl: self.device_proxy,
            write_trl: self.device_proxy,
        }
        self.trl_configs: dict[str, AttributeInfoEx] = {}
        self._polling: tuple[bool, float, float | None, float | None] = (
            False,
            0.1,
            None,
            0.1,
        )
        self.support_events: bool = True
        self.status: AsyncStatus | None = None
        self.converter = TangoConverter()  # gets replaced at connect
        super().__init__(datatype)

    @classmethod
    def datatype_allowed(cls, dtype: Any) -> bool:
        return dtype in (int, float, str, bool, np.ndarray, StrictEnum)

    def set_trl(self, read_trl: str = "", write_trl: str = ""):
        self.read_trl = read_trl
        self.write_trl = write_trl if write_trl else read_trl
        self.proxies = {
            read_trl: self.device_proxy,
            write_trl: self.device_proxy,
        }

    def source(self, name: str, read: bool) -> str:
        return self.read_trl if read else self.write_trl

    def _type_match_ndarray(self, signal_type: type[SignalDatatypeT], tr_dtype: object):
        tango_resource = self.source(name="", read=True)

        def extract_dtype_param(dtype_arg):
            if hasattr(dtype_arg, "__origin__") and dtype_arg.__origin__ is np.dtype:
                inner = get_args(dtype_arg)
                return inner[0] if inner else object
            return dtype_arg

        signal_dtype = extract_dtype_param(get_args(signal_type)[-1])
        tr_dtype_arg = extract_dtype_param(get_args(tr_dtype)[-1])

        try:
            sdt = np.dtype(signal_dtype)
            tdt = np.dtype(tr_dtype_arg)
        except TypeError as e:
            raise TypeError(
                f"Could not interpret array dtypes: {signal_dtype!r},"
                f" {tr_dtype_arg!r} ({e})"
            ) from e

        if sdt != tdt:
            raise TypeError(
                f"{tango_resource} has type {tr_dtype!r}, expected {self.datatype!r}"
            )

    def _type_match_array(
        self,
        signal_type: type[SignalDatatypeT] | None,
        tr_dtype: object,
        tango_resource: str,
    ):
        # Always get a fresh resource string for the error context
        tango_resource = self.source(name="", read=True)
        if get_origin(signal_type) is Sequence and get_origin(tr_dtype) is Sequence:
            sig_elem_type = get_args(signal_type)[0]
            tr_elem_type = get_args(tr_dtype)[0]
            self._type_match_scalar(sig_elem_type, tr_elem_type, tango_resource)
            return
        elif (
            get_origin(signal_type) is np.ndarray and get_origin(tr_dtype) is np.ndarray
        ):
            if signal_type is None:
                raise TypeError(
                    f"{tango_resource} has type {tr_dtype!r}, expected a non-None"
                    f" signal_type"
                )
            self._type_match_ndarray(signal_type, tr_dtype)
            return
        else:
            raise TypeError(
                tango_resource, "has type", str(signal_type), "which is not recognized"
            )

    def _type_match_scalar(
        self,
        signal_type: type[SignalDatatypeT] | None,
        tr_dtype: object,
        tango_resource: str,
    ):
        if signal_type is tr_dtype:
            return
        if isinstance(signal_type, type) and issubclass(signal_type, StrictEnum):
            return
        raise TypeError(
            f"{tango_resource} has type {tr_dtype!r}, expected {self.datatype!r}"
        )

    def _verify_datatype_matches(self, config: AttributeInfoEx | CommandInfo):
        """Verify that the datatype of the config matches the datatype of the signal."""
        tr_dtype = get_python_type(config)
        tango_resource = self.source(name="", read=True)
        signal_type = self.datatype
        if isinstance(config, AttributeInfoEx | AttributeInfo):
            tr_format = config.data_format
            if tr_format in [AttrDataFormat.SPECTRUM, AttrDataFormat.IMAGE]:
                self._type_match_array(signal_type, tr_dtype, tango_resource)
            elif tr_format is AttrDataFormat.SCALAR:
                self._type_match_scalar(signal_type, tr_dtype, tango_resource)
        elif isinstance(config, CommandInfo):
            if (
                config.in_type != CmdArgType.DevVoid
                and config.out_type != CmdArgType.DevVoid
                and config.in_type != config.out_type
            ):
                raise RuntimeError(
                    "Commands with different in and out dtypes are not supported"
                )
            if get_origin(tr_dtype) in [Sequence, np.ndarray]:
                self._type_match_array(signal_type, tr_dtype, tango_resource)
            else:
                self._type_match_scalar(signal_type, tr_dtype, tango_resource)
        else:
            raise TypeError(
                f"Unrecognized resource configuration: {config} "
                f"for source {tango_resource}"
            )

    async def _connect_and_store_config(self, trl: str, timeout: float) -> None:
        if not trl:
            raise RuntimeError(f"trl not set for {self}")
        try:
            self.proxies[trl] = await get_tango_trl(trl, self.proxies[trl], timeout)
            if self.proxies[trl] is None:
                raise NotConnectedError(f"Not connected to {trl}")
            # Pyright does not believe that self.proxies[trl] is not None despite
            # the check above
            await self.proxies[trl].connect()  # type: ignore
            config = await self.proxies[trl].get_config()  # type: ignore
            self.trl_configs[trl] = config

            # Perform signal verification
            self._verify_datatype_matches(config)

            if isinstance(config, AttributeInfoEx):
                if (
                    config.data_type == CmdArgType.DevString
                    and config.data_format == AttrDataFormat.IMAGE
                ):
                    raise TypeError(
                        "DevString IMAGE attributes are not supported by ophyd-async."
                    )
            self.proxies[trl].support_events = self.support_events  # type: ignore
        except TimeoutError as ce:
            raise NotConnectedError(f"tango://{trl}") from ce

    async def connect(self, timeout: float) -> None:
        if not self.read_trl:
            raise RuntimeError(f"trl not set for {self}")
        if self.read_trl != self.write_trl:
            # Different, need to connect both
            await wait_for_connection(
                read_trl=self._connect_and_store_config(self.read_trl, timeout),
                write_trl=self._connect_and_store_config(self.write_trl, timeout),
            )
        else:
            # The same, so only need to connect one
            await self._connect_and_store_config(self.read_trl, timeout)
        self.proxies[self.read_trl].set_polling(*self._polling)  # type: ignore
        self.converter = make_converter(self.trl_configs[self.read_trl], self.datatype)
        self.proxies[self.read_trl].set_converter(self.converter)  # type: ignore

    async def put(self, value: SignalDatatypeT | None, wait=True, timeout=None) -> None:
        if self.proxies[self.write_trl] is None:
            raise NotConnectedError(f"Not connected to {self.write_trl}")
        self.status = None
        put_status = await self.proxies[self.write_trl].put(value, wait, timeout)  # type: ignore
        self.status = put_status

    async def get_datakey(self, source: str) -> DataKey:
        try:
            value: Any = await self.proxies[source].get()  # type: ignore
        except AttributeError as ae:
            raise NotConnectedError(f"Not connected to {source}") from ae
        md = get_source_metadata(source, self.trl_configs)
        return make_datakey(
            self.datatype,  # type: ignore
            value,
            source,
            metadata=md,
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        if self.proxies[self.read_trl] is None:
            raise NotConnectedError(f"Not connected to {self.read_trl}")
        reading = await self.proxies[self.read_trl].get_reading()  # type: ignore
        return reading

    async def get_value(self) -> SignalDatatypeT:
        if self.proxies[self.read_trl] is None:
            raise NotConnectedError(f"Not connected to {self.read_trl}")
        proxy = self.proxies[self.read_trl]
        if proxy is None:
            raise NotConnectedError(f"Not connected to {self.read_trl}")
        value = await proxy.get()
        return cast(SignalDatatypeT, value)

    async def get_setpoint(self) -> SignalDatatypeT:
        if self.proxies[self.write_trl] is None:
            raise NotConnectedError(f"Not connected to {self.write_trl}")
        proxy = self.proxies[self.write_trl]
        if proxy is None:
            raise NotConnectedError(f"Not connected to {self.write_trl}")
        w_value = await proxy.get_w_value()
        return cast(SignalDatatypeT, w_value)

    def set_callback(self, callback: Callback | None) -> None:
        if self.proxies[self.read_trl] is None:
            raise NotConnectedError(f"Not connected to {self.read_trl}")
        if self.support_events is False and self._polling[0] is False:
            raise RuntimeError(
                f"Cannot set event for {self.read_trl}. "
                "Cannot set a callback on an attribute that does not support events and"
                " for which polling is disabled."
            )

        if callback and self.proxies[self.read_trl].has_subscription():  # type: ignore
            msg = "Cannot set a callback when one is already set"
            raise RuntimeError(msg)

        if self.proxies[self.read_trl].has_subscription():  # type: ignore
            self.proxies[self.read_trl].unsubscribe_callback()  # type: ignore

        if callback:
            try:
                self.proxies[self.read_trl].subscribe_callback(callback)  # type: ignore
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Cannot set callback for {self.read_trl}. {exc}"
                ) from exc

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
