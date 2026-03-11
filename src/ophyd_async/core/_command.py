from __future__ import annotations

import asyncio
import inspect
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import (
    Generic,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from unittest.mock import AsyncMock

from ._device import Device, DeviceConnector, LazyMock
from ._signal import SignalDatatypeT
from ._soft_signal_backend import SoftConverter, make_converter
from ._status import AsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    NotConnectedError,
    P,
    T,
    T_co,
    _wait_for,
)


class CommandBackend(Generic[P, T_co]):
    """A backend for a Command."""

    def __init__(self, datatype: type[SignalDatatypeT] | None):
        self.datatype = datatype

    @abstractmethod
    def source(self, name: str) -> str:
        """Return source of command."""

    @abstractmethod
    async def connect(self, timeout: float) -> None:
        """Connect to underlying hardware."""

    @abstractmethod
    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T_co:
        """Execute the command and return its result."""

    @abstractmethod
    def get_return_type(self) -> type[T_co] | None:
        """Return the return type of the command, or None if it returns None."""


class CommandConnector(DeviceConnector):
    """A connector for a Command."""

    def __init__(self, backend: CommandBackend):
        self._init_backend = backend
        self.backend = backend

    async def connect_mock(self, device: Device, mock: LazyMock):
        """Connect the backend in mock mode."""
        self.backend = MockCommandBackend(self._init_backend, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        """Connect the backend to real hardware."""
        self.backend = self._init_backend
        source = self.backend.source(device.name)
        device.log.debug(f"Connecting to {source}")
        try:
            await self.backend.connect(timeout)
        except TimeoutError as exc:
            raise NotConnectedError(f"Timeout connecting to {source}") from exc
        except Exception as exc:
            raise NotConnectedError(f"Error connecting to {source}: {exc}") from exc


class Command(Device, Generic[P, T]):
    """A Device that can execute a command."""

    _connector: CommandConnector

    def __init__(
        self,
        backend: CommandBackend[P, T],
        timeout: float | None = DEFAULT_TIMEOUT,
        name: str = "",
    ):
        super().__init__(name=name, connector=CommandConnector(backend))
        self._timeout = timeout

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

    @AsyncStatus.wrap
    async def trigger(self, timeout: CalculatableTimeout = CALCULATE_TIMEOUT) -> None:
        """Trigger the action and return a status saying when it's done.

        Calls execute() with no arguments and does not return a value.
        Included for to allow for drop-in replacement of a SignalX.

        :param timeout: The timeout for the trigger.
        """
        if timeout == CALCULATE_TIMEOUT:
            timeout = self._timeout
        source = self._connector.backend.source(self.name)
        self.log.debug(f"Putting default value to backend at source {source}")
        await _wait_for(self.execute(*(), **{}), timeout, source)
        self.log.debug(f"Successfully put default value to backend at source {source}")


class SoftCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a Python callback."""

    def __init__(self, command_cb: Callable[P, T | Awaitable[T]]):
        self._command_cb = command_cb
        self._lock = asyncio.Lock()
        self._sig = inspect.signature(command_cb)
        self._params = list(self._sig.parameters.values())
        for p in self._params:
            if p.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"{command_cb.__name__}() must not use"
                    f" *args/**kwargs; "
                    f"got parameter {p.name!r}"
                )
        # Require full annotations
        hints = get_type_hints(command_cb)
        missing = [p.name for p in self._params if p.name not in hints]
        if missing:
            raise TypeError(
                f"{command_cb.__name__}() is missing type annotations for"
                f" parameter(s) "
                f"{missing}. All parameters must be annotated."
            )
        if "return" not in hints:
            raise TypeError(
                f"{command_cb.__name__}() is missing a return type annotation. "
                "The return type must be annotated."
            )
        # Store expected param types by name (runtime contract)
        self._expected_param_types: dict[str, object] = {
            p.name: hints[p.name] for p in self._params
        }
        # Create converters for each parameter during initialization
        self._converters: dict[str, SoftConverter] = {}
        for name, expected_type in self._expected_param_types.items():
            try:
                self._converters[name] = make_converter(expected_type or float)
            except TypeError as exc:
                raise TypeError(
                    f"Cannot create converter for parameter '{name}' of type"
                    f" {expected_type}: {exc}"
                ) from exc
        # Handle return type
        inferred_return = hints["return"]
        if get_origin(inferred_return) in (Awaitable, asyncio.Future):
            inferred_return = get_args(inferred_return)[0]
        if inferred_return is None or inferred_return is type(None):
            _command_return: type[T] | None = None
        else:
            _command_return = cast(type[T], inferred_return)
        super().__init__(datatype=_command_return)

    def source(self, name: str) -> str:
        """Return the source of the command."""
        return f"softcmd://{name}"

    async def connect(self, timeout: float):
        """No-op for SoftCommandBackend."""
        pass

    def get_return_type(self) -> type[T] | None:
        return self.datatype

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the configured callback and return its result."""
        try:
            bound = self._sig.bind(*args, **kwargs)
        except TypeError as exc:
            raise TypeError(str(exc)) from exc
        bound.apply_defaults()
        for name, value in bound.arguments.items():
            converter = self._converters[name]
            try:
                converted_value = converter.write_value(value)
                bound.arguments[name] = converted_value
            except (TypeError, ValueError) as exc:
                expected_type = self._expected_param_types[name]
                raise TypeError(
                    f"Argument '{name}' with value {value!r} is not compatible with "
                    f"expected type {expected_type}: {exc}"
                ) from exc
        async with self._lock:
            result = self._command_cb(*bound.args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return cast(T, result)


class MockCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a mock for testing."""

    def __init__(self, initial_backend: CommandBackend[P, T], mock: LazyMock):
        self._initial_backend = initial_backend
        self._mock = mock
        self._mock_execute_callback: Callable[P, Awaitable[T]] | None = None
        self._return_type = initial_backend.get_return_type()
        self._return_converter: SoftConverter | None = (
            make_converter(self._return_type) if self._return_type is not None else None
        )

    def source(self, name: str) -> str:
        return f"mock+{self._initial_backend.source(name)}"

    def get_return_type(self) -> type[T] | None:
        return self._return_type

    def set_mock_execute_callback(self, callback: Callable[P, Awaitable[T]] | None):
        """Set a callback that will be called when the command is executed."""
        if "execute_mock" in self.__dict__:
            # execute_mock cached property exists, so set the side effect on it
            self.execute_mock.side_effect = callback
        else:
            # execute_mock doesn't exist, don't create it as that would be slow
            # so just keep it internally
            self._mock_execute_callback = callback

    @cached_property
    def execute_mock(self) -> AsyncMock:
        """Return the mock that will track calls to the command execution."""
        execute_mock = AsyncMock(
            name="execute",
            spec=Callable[P, Awaitable[T]],
            side_effect=self._mock_execute_callback
            if self._mock_execute_callback
            else lambda *args, **kwargs: None,
        )
        self._mock().attach_mock(execute_mock, "execute")
        return execute_mock

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the mock command."""
        result = await self.execute_mock(*args, **kwargs)
        if result is None and self._return_converter is not None:
            result = self._return_converter.write_value(None)
        return cast(T, result)

    async def connect(self, timeout: float):
        """Mock backend does not support real connection."""
        raise NotConnectedError("It is not possible to connect a MockCommandBackend")


def soft_command(
    command_cb: Callable[P, T] | Callable[P, Awaitable[T]],
    name: str = "",
    timeout: float | None = DEFAULT_TIMEOUT,
) -> Command[P, T]:
    """Create a Command with a SoftCommandBackend."""
    backend: SoftCommandBackend[P, T] = SoftCommandBackend(command_cb)
    return Command(backend, timeout, name)
