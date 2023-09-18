from __future__ import annotations

import asyncio
import functools
from typing import AsyncGenerator, Callable, Dict, Generic, Optional, Union

from bluesky.protocols import (
    Descriptor,
    Locatable,
    Location,
    Movable,
    Readable,
    Reading,
    Stageable,
    Subscribable,
)

from ...async_status import AsyncStatus
from ...utils import DEFAULT_TIMEOUT, Callback, ReadingValueCallback, T
from .._backend.signal_backend import SignalBackend
from .._backend.sim_signal_backend import SimSignalBackend
from ..device import Device

_sim_backends: Dict[Signal, SimSignalBackend] = {}


def _add_timeout(func):
    @functools.wraps(func)
    async def wrapper(self: Signal, *args, **kwargs):
        return await asyncio.wait_for(func(self, *args, **kwargs), self._timeout)

    return wrapper


def _fail(self, other, *args, **kwargs):
    if isinstance(other, Signal):
        raise TypeError(
            "Can't compare two Signals, did you mean await signal.get_value() instead?"
        )
    else:
        return NotImplemented


class Signal(Device, Generic[T]):
    """A Device with the concept of a value, with R, RW, W and X flavours"""

    def __init__(
        self, backend: SignalBackend[T], timeout: Optional[float] = DEFAULT_TIMEOUT
    ) -> None:
        self._name = ""
        self._timeout = timeout
        self._init_backend = self._backend = backend

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str = ""):
        self._name = name

    async def connect(self, sim=False):
        if sim:
            self._backend = SimSignalBackend(
                datatype=self._init_backend.datatype, source=self._init_backend.source
            )
            _sim_backends[self] = self._backend
        else:
            self._backend = self._init_backend
            _sim_backends.pop(self, None)
        await self._backend.connect()

    @property
    def source(self) -> str:
        """Like ca://PV_PREFIX:SIGNAL, or "" if not set"""
        return self._backend.source

    __lt__ = __le__ = __eq__ = __ge__ = __gt__ = __ne__ = _fail

    def __hash__(self):
        # Restore the default implementation so we can use in a set or dict
        return hash(id(self))


class _SignalCache(Generic[T]):
    def __init__(self, backend: SignalBackend[T], signal: Signal):
        self._signal = signal
        self._staged = False
        self._listeners: Dict[Callback, bool] = {}
        self._valid = asyncio.Event()
        self._reading: Optional[Reading] = None
        self._value: Optional[T] = None

        self.backend = backend
        backend.set_callback(self._callback)

    def close(self):
        self.backend.set_callback(None)

    async def get_reading(self) -> Reading:
        await self._valid.wait()
        assert self._reading is not None, "Monitor not working"
        return self._reading

    async def get_value(self) -> T:
        await self._valid.wait()
        assert self._value is not None, "Monitor not working"
        return self._value

    def _callback(self, reading: Reading, value: T):
        self._reading = reading
        self._value = value
        self._valid.set()
        for function, want_value in self._listeners.items():
            self._notify(function, want_value)

    def _notify(self, function: Callback, want_value: bool):
        if want_value:
            function(self._value)
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


class SignalR(Signal[T], Readable, Stageable, Subscribable):
    """Signal that can be read from and monitored"""

    _cache: Optional[_SignalCache] = None

    def _backend_or_cache(
        self, cached: Optional[bool]
    ) -> Union[_SignalCache, SignalBackend]:
        # If cached is None then calculate it based on whether we already have a cache
        if cached is None:
            cached = self._cache is not None
        if cached:
            assert self._cache, f"{self.source} not being monitored"
            return self._cache
        else:
            return self._backend

    def _get_cache(self) -> _SignalCache:
        if not self._cache:
            self._cache = _SignalCache(self._backend, self)
        return self._cache

    def _del_cache(self, needed: bool):
        if self._cache and not needed:
            self._cache.close()
            self._cache = None

    @_add_timeout
    async def read(self, cached: Optional[bool] = None) -> Dict[str, Reading]:
        """Return a single item dict with the reading in it"""
        return {self.name: await self._backend_or_cache(cached).get_reading()}

    @_add_timeout
    async def describe(self) -> Dict[str, Descriptor]:
        """Return a single item dict with the descriptor in it"""
        return {self.name: await self._backend.get_descriptor()}

    @_add_timeout
    async def get_value(self, cached: Optional[bool] = None) -> T:
        """The current value"""
        return await self._backend_or_cache(cached).get_value()

    def subscribe_value(self, function: Callback[T]):
        """Subscribe to updates in value of a device"""
        self._get_cache().subscribe(function, want_value=True)

    def subscribe(self, function: Callback[Dict[str, Reading]]) -> None:
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


class SignalW(Signal[T], Movable):
    """Signal that can be set"""

    _cache: Optional[_SignalCache] = None

    def _backend_or_cache(
        self, cached: Optional[bool]
    ) -> Union[_SignalCache, SignalBackend]:
        # If cached is None then calculate it based on whether we already have a cache
        if cached is None:
            cached = self._cache is not None
        if cached:
            assert self._cache, f"{self.source} not being monitored"
            return self._cache
        else:
            return self._backend

    def set(self, value: T, wait=True, timeout=None) -> AsyncStatus:
        """Set the value and return a status saying when it's done"""
        coro = self._backend.put(value, wait=wait, timeout=timeout or self._timeout)
        return AsyncStatus(coro)

    @_add_timeout
    async def get_setpoint(self, cached: Optional[bool] = None) -> T:
        """The current value"""
        return await self._backend_or_cache(cached).get_value()


class SignalRW(SignalR[T], SignalW[T], Locatable):
    """Signal that can be both read and set"""

    async def locate(self) -> Location:
        location: Location = {
            "setpoint": await self.get_setpoint(),
            "readback": await self.get_value(),
        }
        return location


class SignalX(Signal):
    """Signal that puts the default value"""

    async def execute(self, wait=True, timeout=None):
        """Execute the action and return a status saying when it's done"""
        await self._backend.put(None, wait=wait, timeout=timeout or self._timeout)


def set_sim_value(signal: Signal[T], value: T):
    """Set the value of a signal that is in sim mode."""
    _sim_backends[signal]._set_value(value)


def set_sim_put_proceeds(signal: Signal[T], proceeds: bool):
    """Allow or block a put with wait=True from proceeding"""
    event = _sim_backends[signal].put_proceeds
    if proceeds:
        event.set()
    else:
        event.clear()


def set_sim_callback(signal: Signal[T], callback: ReadingValueCallback[T]) -> None:
    """Monitor the value of a signal that is in sim mode"""
    return _sim_backends[signal].set_callback(callback)


async def observe_value(signal: SignalR[T]) -> AsyncGenerator[T, None]:
    """Subscribe to the value of a signal so it can be iterated from.

    Parameters
    ----------
    signal:
        Call subscribe_value on this at the start, and clear_sub on it at the
        end

    Notes
    -----
    Example usage::

        async for value in observe_value(sig):
            do_something_with(value)
    """
    q: asyncio.Queue[T] = asyncio.Queue()
    signal.subscribe_value(q.put_nowait)
    try:
        while True:
            yield await q.get()
    finally:
        signal.clear_sub(q.put_nowait)


class _ValueChecker(Generic[T]):
    def __init__(self, matcher: Callable[[T], bool], matcher_name: str):
        self._last_value: Optional[T]
        self._matcher = matcher
        self._matcher_name = matcher_name

    async def _wait_for_value(self, signal: SignalR[T]):
        async for value in observe_value(signal):
            self._last_value = value
            if self._matcher(value):
                return

    async def wait_for_value(self, signal: SignalR[T], timeout: float):
        try:
            await asyncio.wait_for(self._wait_for_value(signal), timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"{signal.name} didn't match {self._matcher_name} in {timeout}s, "
                f"last value {self._last_value!r}"
            ) from e


async def wait_for_value(
    signal: SignalR[T], match: Union[T, Callable[[T], bool]], timeout: float
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
        checker = _ValueChecker(match, match.__name__)
    else:
        checker = _ValueChecker(lambda v: v == match, repr(match))
    await checker.wait_for_value(signal, timeout)


async def set_and_wait_for_value(
    signal: SignalRW[T],
    value: T,
    timeout: float = DEFAULT_TIMEOUT,
    status_timeout: Optional[float] = None,
) -> AsyncStatus:
    """Set a signal and monitor it until it has that value.

    Useful for busy record, or other Signals with pattern:

    - Set Signal with wait=True and stash the Status
    - Read the same Signal to check the operation has started
    - Return the Status so calling code can wait for operation to complete

    Parameters
    ----------
    signal:
        The signal to set and monitor
    value:
        The value to set it to
    timeout:
        How long to wait for the signal to have the value
    status_timeout:
        How long the returned Status will wait for the set to complete

    Notes
    -----
    Example usage::

        set_and_wait_for_value(device.acquire, 1)
    """
    status = signal.set(value, timeout=status_timeout)
    await wait_for_value(signal, value, timeout=timeout)
    return status
