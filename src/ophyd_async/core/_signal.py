from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from typing import Any, Generic, cast

from bluesky.protocols import (
    Locatable,
    Location,
    Movable,
    Status,
    Subscribable,
)
from event_model import DataKey

from ._device import Device, DeviceConnector
from ._mock_signal_backend import MockSignalBackend
from ._protocol import (
    AsyncConfigurable,
    AsyncReadable,
    AsyncStageable,
    Reading,
)
from ._signal_backend import (
    SignalBackend,
    SignalDatatypeT,
    SignalDatatypeV,
)
from ._soft_signal_backend import SoftSignalBackend
from ._status import AsyncStatus, completed_status
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    Callback,
    LazyMock,
    T,
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
        raise AttributeError(
            f"Cannot add Device or Signal child {key}={value} of Signal, "
            "make a subclass of Device instead"
        )


class Signal(Device, Generic[SignalDatatypeT]):
    """A Device with the concept of a value, with R, RW, W and X flavours"""

    _connector: SignalConnector
    _child_devices = _ChildrenNotAllowed()  # type: ignore

    def __init__(
        self,
        backend: SignalBackend[SignalDatatypeT],
        timeout: float | None = DEFAULT_TIMEOUT,
        name: str = "",
    ) -> None:
        super().__init__(name=name, connector=SignalConnector(backend))
        self._timeout = timeout

    @property
    def source(self) -> str:
        """Like ca://PV_PREFIX:SIGNAL, or "" if not set"""
        return self._connector.backend.source(self.name, read=True)


class _SignalCache(Generic[SignalDatatypeT]):
    def __init__(self, backend: SignalBackend[SignalDatatypeT], signal: Signal):
        self._signal = signal
        self._staged = False
        self._listeners: dict[Callback, bool] = {}
        self._valid = asyncio.Event()
        self._reading: Reading[SignalDatatypeT] | None = None
        self.backend = backend
        signal.log.debug(f"Making subscription on source {signal.source}")
        backend.set_callback(self._callback)

    def close(self):
        self.backend.set_callback(None)
        self._signal.log.debug(f"Closing subscription on source {self._signal.source}")

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        await self._valid.wait()
        assert self._reading is not None, "Monitor not working"
        return self._reading

    async def get_value(self) -> SignalDatatypeT:
        reading = await self.get_reading()
        return reading["value"]

    def _callback(self, reading: Reading[SignalDatatypeT]):
        self._signal.log.debug(
            f"Updated subscription: reading of source {self._signal.source} changed "
            f"from {self._reading} to {reading}"
        )
        self._reading = reading
        self._valid.set()
        for function, want_value in self._listeners.items():
            self._notify(function, want_value)

    def _notify(
        self,
        function: Callback[dict[str, Reading[SignalDatatypeT]] | SignalDatatypeT],
        want_value: bool,
    ):
        assert self._reading, "Monitor not working"
        if want_value:
            function(self._reading["value"])
        else:
            function({self._signal.name: self._reading})

    def subscribe(self, function: Callback, want_value: bool) -> None:
        self._listeners[function] = want_value
        if self._valid.is_set():
            self._notify(function, want_value)

    def unsubscribe(self, function: Callback) -> bool:
        self._listeners.pop(function)
        return self._staged or bool(self._listeners)

    def set_staged(self, staged: bool):
        self._staged = staged
        return self._staged or bool(self._listeners)


class SignalR(Signal[SignalDatatypeT], AsyncReadable, AsyncStageable, Subscribable):
    """Signal that can be read from and monitored"""

    _cache: _SignalCache | None = None

    def _backend_or_cache(
        self, cached: bool | None = None
    ) -> _SignalCache | SignalBackend:
        # If cached is None then calculate it based on whether we already have a cache
        if cached is None:
            cached = self._cache is not None
        if cached:
            assert self._cache, f"{self.source} not being monitored"
            return self._cache
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
        """Return a single item dict with the reading in it"""
        return {self.name: await self._backend_or_cache(cached).get_reading()}

    @_add_timeout
    async def describe(self) -> dict[str, DataKey]:
        """Return a single item dict with the descriptor in it"""
        return {self.name: await self._connector.backend.get_datakey(self.source)}

    @_add_timeout
    async def get_value(self, cached: bool | None = None) -> SignalDatatypeT:
        """The current value"""
        value = await self._backend_or_cache(cached).get_value()
        self.log.debug(f"get_value() on source {self.source} returned {value}")
        return value

    def subscribe_value(self, function: Callback[SignalDatatypeT]):
        """Subscribe to updates in value of a device"""
        self._get_cache().subscribe(function, want_value=True)

    def subscribe(self, function: Callback[dict[str, Reading]]) -> None:
        """Subscribe to updates in the reading"""
        self._get_cache().subscribe(function, want_value=False)

    def clear_sub(self, function: Callback) -> None:
        """Remove a subscription."""
        self._del_cache(self._get_cache().unsubscribe(function))

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Start caching this signal"""
        self._get_cache().set_staged(True)

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop caching this signal"""
        self._del_cache(self._get_cache().set_staged(False))


class SignalW(Signal[SignalDatatypeT], Movable):
    """Signal that can be set"""

    @AsyncStatus.wrap
    async def set(
        self,
        value: SignalDatatypeT,
        wait=True,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
    ) -> None:
        """Set the value and return a status saying when it's done"""
        if timeout == CALCULATE_TIMEOUT:
            timeout = self._timeout
        source = self._connector.backend.source(self.name, read=False)
        self.log.debug(f"Putting value {value} to backend at source {source}")
        await _wait_for(self._connector.backend.put(value, wait=wait), timeout, source)
        self.log.debug(f"Successfully put value {value} to backend at source {source}")


class SignalRW(SignalR[SignalDatatypeT], SignalW[SignalDatatypeT], Locatable):
    """Signal that can be both read and set"""

    @_add_timeout
    async def locate(self) -> Location:
        """Return the setpoint and readback."""
        setpoint, readback = await asyncio.gather(
            self._connector.backend.get_setpoint(), self._backend_or_cache().get_value()
        )
        return Location(setpoint=setpoint, readback=readback)


class SignalX(Signal):
    """Signal that puts the default value"""

    @AsyncStatus.wrap
    async def trigger(
        self, wait=True, timeout: CalculatableTimeout = CALCULATE_TIMEOUT
    ) -> None:
        """Trigger the action and return a status saying when it's done"""
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
    """Creates a read-writable Signal with a SoftSignalBackend.
    May pass metadata, which are propagated into describe.
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
    """Returns a tuple of a read-only Signal and a callable through
    which the signal can be internally modified within the device.
    May pass metadata, which are propagated into describe.
    Use soft_signal_rw if you want a device that is externally modifiable
    """
    backend = SoftSignalBackend(datatype, initial_value, units, precision)
    signal = SignalR(backend=backend, name=name)
    return (signal, backend.set_value)


def _generate_assert_error_msg(name: str, expected_result, actual_result) -> str:
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    return (
        f"Expected {WARNING}{name}{ENDC} to produce"
        + f"\n{FAIL}{expected_result}{ENDC}"
        + f"\nbut actually got \n{FAIL}{actual_result}{ENDC}"
    )


async def assert_value(signal: SignalR[SignalDatatypeT], value: Any) -> None:
    """Assert a signal's value and compare it an expected signal.

    Parameters
    ----------
    signal:
        signal with get_value.
    value:
        The expected value from the signal.

    Notes
    -----
    Example usage::
        await assert_value(signal, value)

    """
    actual_value = await signal.get_value()
    assert actual_value == value, _generate_assert_error_msg(
        name=signal.name,
        expected_result=value,
        actual_result=actual_value,
    )


async def assert_reading(
    readable: AsyncReadable, expected_reading: Mapping[str, Reading]
) -> None:
    """Assert readings from readable.

    Parameters
    ----------
    readable:
        Callable with readable.read function that generate readings.

    reading:
        The expected readings from the readable.

    Notes
    -----
    Example usage::
        await assert_reading(readable, reading)

    """
    actual_reading = await readable.read()
    assert expected_reading == actual_reading, _generate_assert_error_msg(
        name=readable.name,
        expected_result=expected_reading,
        actual_result=actual_reading,
    )


async def assert_configuration(
    configurable: AsyncConfigurable,
    configuration: Mapping[str, Reading],
) -> None:
    """Assert readings from Configurable.

    Parameters
    ----------
    configurable:
        Configurable with Configurable.read function that generate readings.

    configuration:
        The expected readings from configurable.

    Notes
    -----
    Example usage::
        await assert_configuration(configurable configuration)

    """
    actual_configurable = await configurable.read_configuration()
    assert configuration == actual_configurable, _generate_assert_error_msg(
        name=configurable.name,
        expected_result=configuration,
        actual_result=actual_configurable,
    )


def assert_emitted(docs: Mapping[str, list[dict]], **numbers: int):
    """Assert emitted document generated by running a Bluesky plan

    Parameters
    ----------
    Doc:
        A dictionary

    numbers:
        expected emission in kwarg from

    Notes
    -----
    Example usage::
        assert_emitted(docs, start=1, descriptor=1,
        resource=1, datum=1, event=1, stop=1)
    """
    assert list(docs) == list(numbers), _generate_assert_error_msg(
        name="documents",
        expected_result=list(numbers),
        actual_result=list(docs),
    )
    actual_numbers = {name: len(d) for name, d in docs.items()}
    assert actual_numbers == numbers, _generate_assert_error_msg(
        name="emitted",
        expected_result=numbers,
        actual_result=actual_numbers,
    )


async def observe_value(
    signal: SignalR[SignalDatatypeT],
    timeout: float | None = None,
    done_status: Status | None = None,
) -> AsyncGenerator[SignalDatatypeT, None]:
    """Subscribe to the value of a signal so it can be iterated from.

    Parameters
    ----------
    signal:
        Call subscribe_value on this at the start, and clear_sub on it at the
        end
    timeout:
        If given, how long to wait for each updated value in seconds. If an update
        is not produced in this time then raise asyncio.TimeoutError
    done_status:
        If this status is complete, stop observing and make the iterator return.
        If it raises an exception then this exception will be raised by the iterator.

    Notes
    -----
    Example usage::

        async for value in observe_value(sig):
            do_something_with(value)
    """

    async for _, value in observe_signals_value(
        signal, timeout=timeout, done_status=done_status
    ):
        yield value


async def observe_signals_value(
    *signals: SignalR[SignalDatatypeT],
    timeout: float | None = None,
    done_status: Status | None = None,
) -> AsyncGenerator[tuple[SignalR[SignalDatatypeT], SignalDatatypeT], None]:
    """Subscribe to the value of a signal so it can be iterated from.

    Parameters
    ----------
    signals:
        Call subscribe_value on all the signals at the start, and clear_sub on it at the
        end
    timeout:
        If given, how long to wait for each updated value in seconds. If an update
        is not produced in this time then raise asyncio.TimeoutError
    done_status:
        If this status is complete, stop observing and make the iterator return.
        If it raises an exception then this exception will be raised by the iterator.

    Notes
    -----
    Example usage::

        async for signal,value in observe_signals_values(sig1,sig2,..):
            if signal is sig1:
                do_something_with(value)
            elif signal is sig2:
                do_something_else_with(value)
    """
    q: asyncio.Queue[tuple[SignalR[SignalDatatypeT], SignalDatatypeT] | Status] = (
        asyncio.Queue()
    )
    if timeout is None:
        get_value = q.get
    else:

        async def get_value():
            return await asyncio.wait_for(q.get(), timeout)

    cbs: dict[SignalR, Callback] = {}
    for signal in signals:

        def queue_value(value: SignalDatatypeT, signal=signal):
            q.put_nowait((signal, value))

        cbs[signal] = queue_value
        signal.subscribe_value(queue_value)

    if done_status is not None:
        done_status.add_callback(q.put_nowait)

    try:
        while True:
            # yield here in case something else is filling the queue
            # like in test_observe_value_times_out_with_no_external_task()
            await asyncio.sleep(0)
            item = await get_value()
            if done_status and item is done_status:
                if exc := done_status.exception():
                    raise exc
                else:
                    break
            else:
                yield cast(tuple[SignalR[SignalDatatypeT], SignalDatatypeT], item)
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
):
    """Wait for a signal to have a matching value.

    Parameters
    ----------
    signal:
        Call subscribe_value on this at the start, and clear_sub on it at the
        end
    match:
        If a callable, it should return True if the value matches. If not
        callable then value will be checked for equality with match.
    timeout:
        How long to wait for the value to match

    Notes
    -----
    Example usage::

        wait_for_value(device.acquiring, 1, timeout=1)

    Or::

        wait_for_value(device.num_captured, lambda v: v > 45, timeout=1)
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

    Parameters
    ----------
    signal:
        The signal to set
    set_value:
        The value to set it to
    match_signal:
        The signal to monitor
    match_value:
        The value to wait for
    timeout:
        How long to wait for the signal to have the value
    set_timeout:
        How long to wait for the set to complete
    wait_for_set_completion:
        This will wait for set completion #More info in how-to docs

    Notes
    -----
    Example usage::

        set_and_wait_for_value(device.acquire, 1, device.acquire_rbv, 1)
    """
    # Start monitoring before the set to avoid a race condition
    values_gen = observe_value(match_signal)

    # Get the initial value from the monitor to make sure we've created it
    current_value = await anext(values_gen)

    status = set_signal.set(set_value, timeout=set_timeout)

    # If the value was the same as before no need to wait for it to change
    if current_value != match_value:

        async def _wait_for_value():
            async for value in values_gen:
                if value == match_value:
                    break

        try:
            await asyncio.wait_for(_wait_for_value(), timeout)
            if wait_for_set_completion:
                await status
            return status
        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"{match_signal.name} didn't match {match_value} in {timeout}s"
            ) from e

    return completed_status()


async def set_and_wait_for_value(
    signal: SignalRW[SignalDatatypeT],
    value: SignalDatatypeT,
    match_value: SignalDatatypeT | Callable[[SignalDatatypeT], bool] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    status_timeout: float | None = None,
    wait_for_set_completion: bool = True,
) -> AsyncStatus:
    """Set a signal and monitor it until it has that value.

    Useful for busy record, or other Signals with pattern:
      - Set Signal with wait=True and stash the Status
      - Read the same Signal to check the operation has started
      - Return the Status so calling code can wait for operation to complete

    Parameters
    ----------
    signal:
        The signal to set
    value:
        The value to set it to
    match_value:
        The expected value of the signal after the operation.
        Used to verify that the set operation was successful.
    timeout:
        How long to wait for the signal to have the value
    status_timeout:
        How long the returned Status will wait for the set to complete
    wait_for_set_completion:
        This will wait for set completion #More info in how-to docs

    Notes
    -----
    Example usage::

        set_and_wait_for_value(device.acquire, 1)
    """
    if match_value is None:
        match_value = value
    return await set_and_wait_for_other_value(
        signal,
        value,
        signal,
        match_value,
        timeout,
        status_timeout,
        wait_for_set_completion,
    )
