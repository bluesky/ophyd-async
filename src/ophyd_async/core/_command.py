from __future__ import annotations

import asyncio
import inspect
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import Generic, cast
from unittest.mock import AsyncMock

from ._device import Device, DeviceConnector, LazyMock
from ._soft_signal_backend import SoftConverter, make_converter
from ._status import AsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    NotConnectedError,
    P,
    T,
    _wait_for,
)

# Canonical signature for no-arg void commands.  Hardware backends (e.g. EPICS)
# pass this instead of None so that mock mode always has a concrete signature to
# work with.  `None` is reserved for "not yet known until connect time".
NO_ARG_VOID_SIGNATURE = inspect.Signature([], return_annotation=None)


MockExecuteCallback = Callable[P, T] | Callable[P, Awaitable[T]]


class CommandBackend(Generic[P, T]):
    """A backend for a Command.

    :param signature: The Python signature of the command, or `None` if the
        signature is not yet known until connect time (analogous to `datatype=None`
        for signals).  Hardware backends that are unambiguously void/void should
        pass `NO_ARG_VOID_SIGNATURE` instead.
    """

    def __init__(self, signature: inspect.Signature | None):
        self.signature = signature

    @abstractmethod
    def source(self, name: str) -> str:
        """Return source of command."""

    @abstractmethod
    async def connect(self, timeout: float) -> None:
        """Connect to underlying hardware."""

    @abstractmethod
    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the command and return its result."""


class CommandConnector(DeviceConnector, Generic[P, T]):
    """A connector for a Command."""

    def __init__(self, backend: CommandBackend[P, T]):
        self.backend = self._init_backend = backend

    async def connect_mock(self, device: Device, mock: LazyMock):
        """Connect the backend in mock mode."""
        self.backend = MockCommandBackend(self._init_backend, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        """Connect the backend to real hardware."""
        self.backend = self._init_backend
        device.log.debug(f"Connecting to {self.backend.source(device.name)}")
        await self.backend.connect(timeout)


class Command(Device, Generic[P, T]):
    """A Device that can execute a command."""

    _connector: CommandConnector[P, T]

    def __init__(
        self,
        backend: CommandBackend[P, T],
        timeout: float | None = DEFAULT_TIMEOUT,
        name: str = "",
    ):
        super().__init__(name=name, connector=CommandConnector(backend))
        self._timeout = timeout

    @property
    def signature(self) -> inspect.Signature | None:
        return self._connector.backend.signature

    @property
    def source(self) -> str:
        """Returns the source of the command."""
        return self._connector.backend.source(self.name)

    @AsyncStatus.wrap
    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Implementation for executing the backend (awaited by AsyncStatus)."""
        self.log.debug(f"Executing command {self.name}")
        result = await _wait_for(
            self._connector.backend.execute(*args, **kwargs), self._timeout, self.source
        )
        self.log.debug(f"Command {self.name} returned {result}")
        return result


class TriggerableCommand(Command[[], None]):
    """A Command that can be triggered without arguments and returns None."""

    @AsyncStatus.wrap
    async def trigger(self, timeout: CalculatableTimeout = CALCULATE_TIMEOUT) -> None:
        """Trigger the action and return a status saying when it's done."""
        if timeout == CALCULATE_TIMEOUT:
            timeout = self._timeout
        source = self._connector.backend.source(self.name)
        self.log.debug(f"Putting default value to backend at source {source}")
        await _wait_for(self._connector.backend.execute(), timeout, source)
        self.log.debug(f"Successfully put default value to backend at source {source}")


class SoftCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a Python callback.

    Concurrent calls to `execute()` are serialised by an internal lock: a second
    caller blocks until the first finishes.  This is intentional — hardware
    commands should not run concurrently, and it prevents re-entrant callback
    invocations.
    """

    signature: inspect.Signature

    def __init__(
        self,
        command_cb: Callable[P, T] | Callable[P, Awaitable[T]],
        sig: inspect.Signature,
    ):
        self.command_cb = command_cb
        self._lock = asyncio.Lock()
        params = list(sig.parameters.values())
        for p in params:
            if p.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"{command_cb.__name__}() must not use *args/**kwargs; "
                    f"got parameter {p.name!r}"
                )
        missing = [p.name for p in params if p.annotation is inspect.Parameter.empty]
        if missing:
            raise TypeError(
                f"{command_cb.__name__}() missing type annotations for parameter(s) "
                f"{missing}. All parameters must be annotated."
            )
        if sig.return_annotation is inspect.Parameter.empty:
            raise TypeError(
                f"{command_cb.__name__}() missing a return type annotation. "
                "The return type must be annotated."
            )
        self._expected_param_types: dict[str, object] = {
            p.name: p.annotation for p in params
        }
        self._converters: dict[str, SoftConverter] = {}
        for name, expected_type in self._expected_param_types.items():
            try:
                self._converters[name] = make_converter(expected_type)
            except TypeError as exc:
                raise TypeError(
                    f"Cannot create converter for parameter '{name}' of type"
                    f" {expected_type}: {exc}"
                ) from exc
        super().__init__(signature=sig)

    def source(self, name: str) -> str:
        """Return the source of the command."""
        return f"softcmd://{name}"

    async def connect(self, timeout: float) -> None:
        """No-op for SoftCommandBackend."""
        pass

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the configured callback and return its result."""
        try:
            bound = self.signature.bind(*args, **kwargs)
        except TypeError as exc:
            raise TypeError(str(exc)) from exc
        bound.apply_defaults()
        for name, value in bound.arguments.items():
            try:
                bound.arguments[name] = self._converters[name].write_value(value)
            except (TypeError, ValueError) as exc:
                expected_type = self._expected_param_types[name]
                raise TypeError(
                    f"Argument '{name}' with value {value!r} is not compatible"
                    f" with expected type {expected_type}: {exc}"
                ) from exc
        async with self._lock:
            result = self.command_cb(*bound.args, **bound.kwargs)
            if inspect.isawaitable(result):
                return await result
            else:
                return result


class MockCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a mock for testing."""

    def __init__(self, initial_backend: CommandBackend[P, T], mock: LazyMock):
        self._initial_backend = initial_backend
        self._mock = mock
        self._mock_execute_callback: MockExecuteCallback[P, T] | None = None
        sig = initial_backend.signature or NO_ARG_VOID_SIGNATURE

        # Build a SoftCommandBackend from the signature and a closure that
        # forwards converted calls to execute_mock — same pattern as
        # MockSignalBackend wrapping a SoftSignalBackend for type conversion.
        # The lambda defers access to execute_mock to keep it lazy-initialised.
        self._soft_backend: SoftCommandBackend[P, T] = SoftCommandBackend(
            command_cb=lambda *args, **kwargs: self.execute_mock(*args, **kwargs),
            sig=sig,
        )

        self._return_converter: SoftConverter | None = (
            make_converter(sig.return_annotation)
            if sig.return_annotation not in (None, inspect.Parameter.empty)
            else None
        )
        super().__init__(signature=sig)

    def source(self, name: str) -> str:
        return f"mock+{self._initial_backend.source(name)}"

    def set_mock_execute_callback(self, callback: MockExecuteCallback[P, T] | None):
        """Set a callback that will be called when the command is executed.

        Pass `None` to restore the default side effect (the original callable for
        `SoftCommandBackend`, or a manufactured default for hardware backends).
        """
        self._mock_execute_callback = callback
        if "execute_mock" in self.__dict__:
            self.execute_mock.side_effect = self._make_side_effect()

    def _make_side_effect(self) -> Callable[P, T] | Callable[P, Awaitable[T]]:
        if self._mock_execute_callback is not None:
            return self._mock_execute_callback
        elif isinstance(self._initial_backend, SoftCommandBackend):
            # Args arrive already converted by _soft_backend, so call _command_cb
            # directly rather than going through execute() again (which would
            # convert a second time and re-acquire the lock).
            return self._initial_backend.command_cb
        elif self._return_converter is None:
            return lambda *args, **kwargs: cast(T, None)
        else:
            rc = self._return_converter
            return lambda *args, **kwargs: rc.write_value(None)

    @cached_property
    def execute_mock(self) -> AsyncMock:
        """Return the mock that will track calls to the command execution."""
        execute_mock = AsyncMock(name="execute", side_effect=self._make_side_effect())
        self._mock().attach_mock(execute_mock, "execute")
        return execute_mock

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the mock command converting arguments as SoftCommandBackend would."""
        return await self._soft_backend.execute(*args, **kwargs)

    async def connect(self, timeout: float) -> None:
        """Mock backend does not support real connection."""
        raise NotConnectedError("It is not possible to connect a MockCommandBackend")


def soft_command(
    command_cb: Callable[P, T] | Callable[P, Awaitable[T]],
    name: str = "",
    timeout: float | None = DEFAULT_TIMEOUT,
) -> Command[P, T]:
    """Create a Command with a SoftCommandBackend."""
    # eval_str=True resolves forward-reference string annotations created by
    # ``from __future__ import annotations`` in the caller's module.
    sig = inspect.signature(command_cb, eval_str=True)
    backend = SoftCommandBackend(command_cb, sig)
    return Command(backend, timeout, name)
