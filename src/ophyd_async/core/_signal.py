from __future__ import annotations

import asyncio
import functools
import inspect
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Generic, TypeVar, cast

from bluesky.protocols import (
    Configurable,
    Locatable,
    Location,
    Movable,
    Reading,
    Status,
    Subscribable,
)
from event_model import DataKey
from stamina import retry_context

from ._device import Device, DeviceConnector
from ._mock_signal_backend import MockSignalBackend
from ._protocol import AsyncReadable, AsyncStageable
from ._signal_backend import SignalBackend, SignalDatatypeT, SignalDatatypeV
from ._soft_signal_backend import SoftSignalBackend
from ._status import AsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    Callback,
    LazyMock,
    T,
    error_if_none,
)


async def _wait_for(coro: Awaitable[T], timeout: float | None, source: str) -> T:
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError as e:
        raise asyncio.TimeoutError(source) from e


def _add_timeout(func):
    @functools.wraps(func)
    async def wrapper(self: Signal, *args, **kwargs):
        return await _wait_for(func(self, *args, **kwargs), self._timeout, self.source)

    return wrapper


class SignalConnector(DeviceConnector):
    """Used for connecting signals with a given backend."""

    def __init__(self, backend: SignalBackend):
        self.backend = self._init_backend = backend

    async def connect_mock(self, device: Device, mock: LazyMock):
        self.backend = MockSignalBackend(self._init_backend, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        self.backend = self._init_backend
        device.log.debug(f"Connecting to {self.backend.source(device.name, read=True)}")
        await self.backend.connect(timeout)


class _ChildrenNotAllowed(dict[str, Device]):
    def __setitem__(self, key: str, value: Device) -> None:
        raise KeyError(
            f"Cannot add Device or Signal child {key}={value} of Signal, "
            "make a subclass of Device instead"
        )


class Signal(Device, Generic[SignalDatatypeT]):
    """A Device with the concept of a value, with R, RW, W and X flavours.

    :param backend: The backend for providing Signal values.
    :param timeout: The default timeout for operations on the Signal.
    :param name: The name of the signal.
    """

    _connector: SignalConnector
    _child_devices = _ChildrenNotAllowed()  # type: ignore

    def __init__(
        self,
        backend: SignalBackend[SignalDatatypeT],
        timeout: float | None = DEFAULT_TIMEOUT,
        name: str = "",
        attempts: int = 1,
    ) -> None:
        super().__init__(name=name, connector=SignalConnector(backend))
        self._timeout = timeout
        self._attempts = attempts

    @property
    def source(self) -> str:
        """Returns the source of the signal.

        E.g. "ca://PV_PREFIX:SIGNAL", or "" if not available until connection.
        """
        return self._connector.backend.source(self.name, read=True)

    @property
    def datatype(self) -> type[SignalDatatypeT] | None:
        """Returns the datatype of the signal."""
        return self._connector.backend.datatype


SignalT = TypeVar("SignalT", bound=Signal)


class _SignalCache(Generic[SignalDatatypeT]):
    def __init__(self, backend: SignalBackend[SignalDatatypeT], signal: Signal) -> None:
        self._signal: Signal[Any] = signal
        self._staged = False
        self._listeners: dict[Callback, bool] = {}
        self._valid = asyncio.Event()
        self._reading: Reading[SignalDatatypeT] | None = None
        self.backend: SignalBackend[SignalDatatypeT] = backend
        signal.log.debug(f"Making subscription on source {signal.source}")
        backend.set_callback(self._callback)

    def close(self) -> None:
        self.backend.set_callback(None)
        self._signal.log.debug(f"Closing subscription on source {self._signal.source}")

    def _ensure_reading(self) -> Reading[SignalDatatypeT]:
        reading = error_if_none(self._reading, "Monitor not working")
        return reading

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        await self._valid.wait()
        return self._ensure_reading()

    async def get_value(self) -> SignalDatatypeT:
        reading: Reading[SignalDatatypeT] = await self.get_reading()
        return reading["value"]

    def _callback(self, reading: Reading[SignalDatatypeT]) -> None:
        self._signal.log.debug(
            f"Updated subscription: reading of source {self._signal.source} changed "
            f"from {self._reading} to {reading}"
        )
        self._reading = reading
        self._valid.set()
        items = self._listeners.copy().items()
        for function, want_value in items:
            self._notify(function, want_value)

    def _notify(
        self,
        function: Callback[dict[str, Reading[SignalDatatypeT]] | SignalDatatypeT],
        want_value: bool,
    ) -> None:
        function(self._ensure_reading()["value"]) if want_value else function(
            {self._signal.name: self._ensure_reading()}
        )

    def subscribe(self, function: Callback, want_value: bool) -> None:
        self._listeners[function] = want_value
        if self._valid.is_set():
            self._notify(function, want_value)

    def unsubscribe(self, function: Callback) -> bool:
        _listener = self._listeners.pop(function, None)
        if not _listener:
            self._signal.log.warning(
                f"Unsubscribe failed: subscriber {function} was not found "
                f" in listeners list: {list(self._listeners)}"
            )
        return self._staged or bool(self._listeners)

    def set_staged(self, staged: bool) -> bool:
        self._staged = staged
        return self._staged or bool(self._listeners)


class SignalR(Signal[SignalDatatypeT], AsyncReadable, AsyncStageable, Subscribable):
    """Signal that can be read from and monitored."""

    _cache: _SignalCache | None = None

    def _backend_or_cache(
        self, cached: bool | None = None
    ) -> _SignalCache | SignalBackend:
        # If cached is None then calculate it based on whether we already have a cache
        if cached is None:
            cached = self._cache is not None
        if cached:
            cache = error_if_none(self._cache, f"{self.source} not being monitored")
            return cache
        else:
            return self._connector.backend

    def _get_cache(self) -> _SignalCache:
        if not self._cache:
            self._cache = _SignalCache(self._connector.backend, self)
        return self._cache

    def _del_cache(self, needed: bool):
        if self._cache and not needed:
            self._cache.close()
            self._cache = None

    @_add_timeout
    async def read(self, cached: bool | None = None) -> dict[str, Reading]:
        """Return a single item dict with the reading in it.

        :param cached:
            Whether to use the cached monitored value:
            - If None, use the cache if it exists.
            - If False, do an explicit get.
            - If True, explicitly use the cache and raise an error if it doesn't exist.
        """
        return {self.name: await self._backend_or_cache(cached).get_reading()}

    @_add_timeout
    async def describe(self) -> dict[str, DataKey]:
        """Return a single item dict describing the signal value."""
        return {self.name: await self._connector.backend.get_datakey(self.source)}

    @_add_timeout
    async def get_value(self, cached: bool | None = None) -> SignalDatatypeT:
        """Return the current value.

        :param cached:
            Whether to use the cached monitored value:
            - If None, use the cache if it exists.
            - If False, do an explicit get.
            - If True, explicitly use the cache and raise an error if it doesn't exist.
        """
        value = await self._backend_or_cache(cached).get_value()
        self.log.debug(f"get_value() on source {self.source} returned {value}")
        return value

    def subscribe_value(self, function: Callback[SignalDatatypeT]):
        """Subscribe to updates in value of a device.

        :param function: The callback function to call when the value changes.
        """
        self._get_cache().subscribe(function, want_value=True)

    def subscribe(
        self, function: Callback[dict[str, Reading[SignalDatatypeT]]]
    ) -> None:
        """Subscribe to updates in the reading.

        :param function: The callback function to call when the reading changes.
        """
        self._get_cache().subscribe(function, want_value=False)

    def clear_sub(self, function: Callback) -> None:
        """Remove a subscription passed to `subscribe` or `subscribe_value`.

        :param function: The callback function to remove.
        """
        self._del_cache(self._get_cache().unsubscribe(function))

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Start caching this signal."""
        self._get_cache().set_staged(True)

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop caching this signal."""
        self._del_cache(self._get_cache().set_staged(False))


class SignalW(Signal[SignalDatatypeT], Movable):
    """Signal that can be set."""

    @AsyncStatus.wrap
    async def set(
        self,
        value: SignalDatatypeT,
        wait=True,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
    ) -> None:
        """Set the value and return a status saying when it's done.

        :param value: The value to set.
        :param wait: If True, wait for the set to complete.
        :param timeout: The timeout for the set.
        """
        if timeout == CALCULATE_TIMEOUT:
            timeout = self._timeout
        source = self._connector.backend.source(self.name, read=False)
        self.log.debug(f"Putting value {value} to backend at source {source}")
        async for attempt in retry_context(
            on=asyncio.TimeoutError,
            attempts=self._attempts,
            wait_initial=0,
            wait_jitter=0,
        ):
            with attempt:
                await _wait_for(
                    self._connector.backend.put(value, wait=wait), timeout, source
                )
        self.log.debug(f"Successfully put value {value} to backend at source {source}")


class SignalRW(SignalR[SignalDatatypeT], SignalW[SignalDatatypeT], Locatable):
    """Signal that can be both read and set."""

    @_add_timeout
    async def locate(self) -> Location:
        """Return the setpoint and readback."""
        setpoint, readback = await asyncio.gather(
            self._connector.backend.get_setpoint(), self._backend_or_cache().get_value()
        )
        return Location(setpoint=setpoint, readback=readback)


class SignalX(Signal):
    """Signal that puts the default value."""

    @AsyncStatus.wrap
    async def trigger(
        self, wait=True, timeout: CalculatableTimeout = CALCULATE_TIMEOUT
    ) -> None:
        """Trigger the action and return a status saying when it's done.

        :param wait: If True, wait for the trigger to complete.
        :param timeout: The timeout for the trigger.
        """
        if timeout == CALCULATE_TIMEOUT:
            timeout = self._timeout
        source = self._connector.backend.source(self.name, read=False)
        self.log.debug(f"Putting default value to backend at source {source}")
        await _wait_for(self._connector.backend.put(None, wait=wait), timeout, source)
        self.log.debug(f"Successfully put default value to backend at source {source}")


def soft_signal_rw(
    datatype: type[SignalDatatypeT],
    initial_value: SignalDatatypeT | None = None,
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> SignalRW[SignalDatatypeT]:
    """Create a read-writable Signal with a [](#SoftSignalBackend).

    May pass metadata, which are propagated into describe.

    :param datatype: The datatype of the signal.
    :param initial_value: The initial value of the signal.
    :param name: The name of the signal.
    :param units: The units of the signal.
    :param precision: The precision of the signal.
    """
    backend = SoftSignalBackend(datatype, initial_value, units, precision)
    signal = SignalRW(backend=backend, name=name)
    return signal


def soft_signal_r_and_setter(
    datatype: type[SignalDatatypeT],
    initial_value: SignalDatatypeT | None = None,
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> tuple[SignalR[SignalDatatypeT], Callable[[SignalDatatypeT], None]]:
    """Create a read-only Signal with a [](#SoftSignalBackend).

    May pass metadata, which are propagated into describe.
    Use soft_signal_rw if you want a device that is externally modifiable.

    :param datatype: The datatype of the signal.
    :param initial_value: The initial value of the signal.
    :param name: The name of the signal.
    :param units: The units of the signal.
    :param precision: The precision of the signal.
    :return: A tuple of the created SignalR and a callable to set its value.
    """
    backend = SoftSignalBackend(datatype, initial_value, units, precision)
    signal = SignalR(backend=backend, name=name)
    return (signal, backend.set_value)


async def observe_value(
    signal: SignalR[SignalDatatypeT],
    timeout: float | None = None,
    done_status: Status | None = None,
    done_timeout: float | None = None,
) -> AsyncGenerator[SignalDatatypeT, None]:
    """Subscribe to the value of a signal so it can be iterated from.

    The first value yielded in the iterator will be the current value of the
    Signal, and subsequent updates from the control system will result in that
    value being yielded, even if it is the same as the previous value.

    :param signal:
        Call subscribe_value on this at the start, and clear_sub on it at the end.
    :param timeout:
        If given, how long to wait for each updated value in seconds. If an
        update is not produced in this time then raise asyncio.TimeoutError.
    :param done_status:
        If this status is complete, stop observing and make the iterator return.
        If it raises an exception then this exception will be raised by the
        iterator.
    :param done_timeout:
        If given, the maximum time to watch a signal, in seconds. If the loop is
        still being watched after this length, raise asyncio.TimeoutError. This
        should be used instead of on an 'asyncio.wait_for' timeout.

    Due to a rare condition with busy signals, it is not recommended to use this
    function with asyncio.timeout, including in an `asyncio.wait_for` loop.
    Instead, this timeout should be given to the done_timeout parameter.

    :example:
    ```python
    async for value in observe_value(sig):
        do_something_with(value)
    ```
    """
    async for _, value in observe_signals_value(
        signal,
        timeout=timeout,
        done_status=done_status,
        done_timeout=done_timeout,
    ):
        yield value


def _get_iteration_timeout(
    timeout: float | None, overall_deadline: float | None
) -> float | None:
    overall_deadline = overall_deadline - time.monotonic() if overall_deadline else None
    return min([x for x in [overall_deadline, timeout] if x is not None], default=None)


async def observe_signals_value(
    *signals: SignalR[SignalDatatypeT],
    timeout: float | None = None,
    done_status: Status | None = None,
    done_timeout: float | None = None,
) -> AsyncGenerator[tuple[SignalR[SignalDatatypeT], SignalDatatypeT], None]:
    """Subscribe to a set of signals so they can be iterated from.

    The first values yielded in the iterator will be the current values of the
    Signals, and subsequent updates from the control system will result in that
    value being yielded, even if it is the same as the previous value.

    :param signals:
        Call subscribe_value on all the signals at the start, and clear_sub on
        it at the end.
    :param timeout:
        If given, how long to wait for ANY updated value from shared queue in seconds.
        If an update is not produced in this time then raise asyncio.TimeoutError.
    :param done_status:
        If this status is complete, stop observing and make the iterator return.
        If it raises an exception then this exception will be raised by the
        iterator.
    :param done_timeout:
        If given, the maximum time to watch a signal, in seconds. If the loop is
        still being watched after this length, raise asyncio.TimeoutError. This
        should be used instead of on an `asyncio.wait_for` timeout.

    :example:
    ```python
    async for signal, value in observe_signals_values(sig1, sig2, ..):
        if signal is sig1:
            do_something_with(value)
        elif signal is sig2:
            do_something_else_with(value)
    ```
    """
    q: asyncio.Queue[tuple[SignalR[SignalDatatypeT], SignalDatatypeT] | Status] = (
        asyncio.Queue()
    )
    # dict to store signal subscription to remove it later
    cbs: dict[SignalR, Callback] = {}

    # subscribe signal to update queue and fill cbs dict
    for signal in signals:

        def queue_value(value: SignalDatatypeT, signal=signal):
            q.put_nowait((signal, value))

        cbs[signal] = queue_value
        signal.subscribe_value(queue_value)

    if done_status is not None:
        done_status.add_callback(q.put_nowait)
    overall_deadline = time.monotonic() + done_timeout if done_timeout else None
    try:
        last_item = ()
        while True:
            if overall_deadline and time.monotonic() >= overall_deadline:
                raise asyncio.TimeoutError(
                    f"observe_value was still observing signals "
                    f"{[signal.source for signal in signals]} after "
                    f"timeout {done_timeout}s"
                )
            iteration_timeout = _get_iteration_timeout(timeout, overall_deadline)
            try:
                item = await asyncio.wait_for(q.get(), iteration_timeout)
            except asyncio.TimeoutError as exc:
                raise asyncio.TimeoutError(
                    f"Timeout Error while waiting {iteration_timeout}s to update "
                    f"{[signal.source for signal in signals]}. "
                    f"Last observed signal and value were {last_item}"
                ) from exc
            if done_status and item is done_status:
                if exc := done_status.exception():
                    raise exc
                else:
                    break
            else:
                last_item = cast(tuple[SignalR[SignalDatatypeT], SignalDatatypeT], item)
                yield last_item
    finally:
        for signal, cb in cbs.items():
            signal.clear_sub(cb)


class _ValueChecker(Generic[SignalDatatypeT]):
    def __init__(self, matcher: Callable[[SignalDatatypeT], bool], matcher_name: str):
        self._last_value: SignalDatatypeT | None = None
        self._matcher = matcher
        self._matcher_name = matcher_name

    async def _wait_for_value(self, signal: SignalR[SignalDatatypeT]):
        async for value in observe_value(signal):
            self._last_value = value
            if self._matcher(value):
                return

    async def wait_for_value(
        self, signal: SignalR[SignalDatatypeT], timeout: float | None
    ):
        try:
            await asyncio.wait_for(self._wait_for_value(signal), timeout)
        except asyncio.TimeoutError as e:
            raise asyncio.TimeoutError(
                f"{signal.name} didn't match {self._matcher_name} in {timeout}s, "
                f"last value {self._last_value!r}"
            ) from e


async def wait_for_value(
    signal: SignalR[SignalDatatypeT],
    match: SignalDatatypeT | Callable[[SignalDatatypeT], bool],
    timeout: float | None,
) -> None:
    """Wait for a signal to have a matching value.

    :param signal:
        Call subscribe_value on this at the start, and clear_sub on it at the
        end.
    :param match:
        If a callable, it should return True if the value matches. If not
        callable then value will be checked for equality with match.
    :param timeout: How long to wait for the value to match.

    :example:
    ```python
    await wait_for_value(device.acquiring, 1, timeout=1)
    # or
    await wait_for_value(device.num_captured, lambda v: v > 45, timeout=1)
    ```
    """
    if callable(match):
        checker = _ValueChecker(match, match.__name__)  # type: ignore
    else:
        checker = _ValueChecker(lambda v: v == match, repr(match))
    await checker.wait_for_value(signal, timeout)


async def set_and_wait_for_other_value(
    set_signal: SignalW[SignalDatatypeT],
    set_value: SignalDatatypeT,
    match_signal: SignalR[SignalDatatypeV],
    match_value: SignalDatatypeV | Callable[[SignalDatatypeV], bool],
    timeout: float = DEFAULT_TIMEOUT,
    set_timeout: float | None = None,
    wait_for_set_completion: bool = True,
) -> AsyncStatus:
    """Set a signal and monitor another signal until it has the specified value.

    This function sets a set_signal to a specified set_value and waits for
    a match_signal to have the match_value.

    :param set_signal: The signal to set.
    :param set_value: The value to set it to.
    :param match_signal: The signal to monitor.
    :param match_value:
        The value (or callable that says if the value matches) to wait for.
    :param timeout: How long to wait for the signal to have the value.
    :param set_timeout: How long to wait for the set to complete.
    :param wait_for_set_completion:
        If False then return as soon as the match_signal matches match_value. If
        True then also wait for the set operation to complete before returning.

    :seealso:
    [](#interact-with-signals)

    :example:
    To set the setpoint and wait for the readback to match:
    ```python
    await set_and_wait_for_value(device.setpoint, 1, device.readback, 1)
    ```
    """
    # Start monitoring before the set to avoid a race condition
    values_gen = observe_value(match_signal)

    # Get the initial value from the monitor to make sure we've created it
    current_value = await anext(values_gen)

    status = set_signal.set(set_value, timeout=set_timeout)

    if callable(match_value):
        matcher: Callable[[SignalDatatypeV], bool] = match_value  # type: ignore
    else:

        def matcher(value):
            return value == match_value

        matcher.__name__ = f"equals_{match_value}"

    # If the value was the same as before no need to wait for it to change
    if not matcher(current_value):

        async def _wait_for_value():
            async for value in values_gen:
                if matcher(value):
                    break

        try:
            await asyncio.wait_for(_wait_for_value(), timeout)
            if wait_for_set_completion:
                await status
        except asyncio.TimeoutError as e:
            raise asyncio.TimeoutError(
                f"{match_signal.name} value didn't match value from"
                f" {matcher.__name__}() in {timeout}s"
            ) from e

    return status


async def set_and_wait_for_value(
    signal: SignalRW[SignalDatatypeT],
    value: SignalDatatypeT,
    match_value: SignalDatatypeT | Callable[[SignalDatatypeT], bool] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    set_timeout: float | None = None,
    wait_for_set_completion: bool = True,
) -> AsyncStatus:
    """Set a signal and monitor that same signal until it has the specified value.

    This function sets a set_signal to a specified set_value and waits for
    a match_signal to have the match_value.

    :param signal: The signal to set.
    :param value: The value to set it to.
    :param match_value:
        The value (or callable that says if the value matches) to wait for.
    :param timeout: How long to wait for the signal to have the value.
    :param set_timeout: How long to wait for the set to complete.
    :param wait_for_set_completion:
        If False then return as soon as the match_signal matches match_value. If
        True then also wait for the set operation to complete before returning.

    :seealso:
    [](#interact-with-signals)

    :examples:
    To set a parameter and wait for it's value to change:
    ```python
    await set_and_wait_for_value(device.parameter, 1)
    ```
    For busy record, or other Signals with pattern:
      - Set Signal with `wait=True` and stash the Status
      - Read the same Signal to check the operation has started
      - Return the Status so calling code can wait for operation to complete
    ```python
    status = await set_and_wait_for_value(
        device.acquire, 1, wait_for_set_completion=False
    )
    # device is now acquiring
    await status
    # device has finished acquiring
    ```
    """
    if match_value is None:
        match_value = value
    return await set_and_wait_for_other_value(
        signal,
        value,
        signal,
        match_value,
        timeout,
        set_timeout,
        wait_for_set_completion,
    )


def walk_rw_signals(device: Device) -> dict[str, SignalRW[Any]]:
    """Retrieve all SignalRWs from a device.

    Stores retrieved signals with their dotted attribute paths in a dictionary. Used as
    part of saving and loading a device.

    :param device: Device to retrieve read-write signals from.
    :param path_prefix: For internal use, leave blank when calling the method.
    :return:
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself.
    """
    all_devices = walk_devices(device)
    return {path: dev for path, dev in all_devices.items() if type(dev) is SignalRW}


async def walk_config_signals(
    device: Device,
) -> dict[str, SignalRW[Any]]:
    """Retrieve all configuration signals from a device.

    Stores retrieved signals with their dotted attribute paths in a dictionary. Used as
    part of saving and loading a device.

    :param device: Device to retrieve configuration signals from.
    :return:
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself.
    """
    config_names: list[str] = []
    if isinstance(device, Configurable):
        configuration = device.read_configuration()
        if inspect.isawaitable(configuration):
            configuration = await configuration
        config_names = list(configuration.keys())

    all_devices = walk_devices(device)
    return {
        path: dev
        for path, dev in all_devices.items()
        if isinstance(dev, SignalRW) and dev.name in config_names
    }


class Ignore:
    """Annotation to ignore a signal when connecting a device."""

    pass


def walk_devices(device: Device, path_prefix: str = "") -> dict[str, Device]:
    """Recursively retrieve all Devices from a device tree.

    :param device: Root device to start from.
    :param path_prefix: For internal use, leave blank when calling the method.
    :return: A dictionary mapping dotted attribute paths to Device instances.
    """
    devices: dict[str, Device] = {}
    for attr_name, attr in device.children():
        dot_path = f"{path_prefix}{attr_name}"
        devices[dot_path] = attr
        devices.update(walk_devices(attr, path_prefix=dot_path + "."))
    return devices


def walk_signal_sources(device: Device) -> dict[str, str]:
    """Recursively gather the `source` field from every Signal in a device tree.

    :param device: Root device to start from.
    :param path_prefix: For internal use, leave blank when calling the method.
    :return: A dictionary mapping dotted attribute paths to Signal source strings.
    """
    all_devices = walk_devices(device)
    return {
        path: dev.source for path, dev in all_devices.items() if isinstance(dev, Signal)
    }
