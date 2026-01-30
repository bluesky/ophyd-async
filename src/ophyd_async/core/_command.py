from __future__ import annotations

import asyncio
import inspect
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from typing import (
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from unittest.mock import AsyncMock

from ._device import Device, DeviceConnector, LazyMock
from ._utils import DEFAULT_TIMEOUT, NotConnectedError, T


async def _wait_for(coro: Awaitable[T], timeout: float | None, source: str) -> T:
    try:
        return await asyncio.wait_for(coro, timeout)
    except TimeoutError as exc:
        raise TimeoutError(source) from exc


P = ParamSpec("P")
T_co = TypeVar("T_co", covariant=True)


class CommandBackend(Protocol[P, T_co]):
    """A backend for a Command."""

    @abstractmethod
    def source(self, name: str) -> str:
        """Return source of command."""

    @abstractmethod
    async def connect(self, timeout: float) -> None:
        """Connect to underlying hardware."""

    @abstractmethod
    async def call(self, *args: P.args, **kwargs: P.kwargs) -> T_co:
        """Execute the command and return its result."""


class CommandConnector(DeviceConnector):
    """A connector for a Command."""

    def __init__(self, backend: CommandBackend):
        self.backend = backend

    async def connect_mock(self, device: Device, mock: LazyMock):
        """Connect the backend in mock mode."""
        self.backend = MockCommandBackend(self.backend, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        """Connect the backend to real hardware."""
        source = self.backend.source(device.name)
        device.log.debug(f"Connecting to {source}")
        try:
            await self.backend.connect(timeout)
        except TimeoutError as exc:
            raise NotConnectedError(f"Timeout connecting to {source}") from exc
        except Exception as exc:
            raise NotConnectedError(f"Error connecting to {source}: {exc}") from exc


class Command(Device, Generic[P, T]):
    """A Device that can be called to execute a command.

    :param backend: The backend for executing the command.
    :param timeout: The default timeout for calling the command.
    :param name: The name of the command.
    """

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

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the command."""
        self.log.debug(
            f"Calling command {self.name} with args {args} and kwargs {kwargs}"
        )
        result = await _wait_for(
            self._connector.backend.call(*args, **kwargs), self._timeout, self.source
        )
        self.log.debug(f"Command {self.name} returned {result}")
        return result


def soft_command(
    command_cb: Callable[P, T | Awaitable[T]],
    command_args: Sequence[type] | None = None,
    command_return: type[T] | None = None,
    name: str = "",
    timeout: float | None = DEFAULT_TIMEOUT,
) -> Command[P, T]:
    """Create a Command with a SoftCommandBackend.

    :param command_cb: The callback function to execute when the command is called.
    :param command_args: Types of the arguments the command takes.
    :param command_return: The type of the value the command returns.
    :param name: The name of the command.
    :param timeout: The default timeout for calling the command.
    """
    backend: SoftCommandBackend[P, T] = SoftCommandBackend(
        command_args, command_return, command_cb
    )
    return Command(backend, timeout, name)


class SoftCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a Python callback."""

    def __init__(
        self,
        command_args: Sequence[type] | None,
        command_return: type[T] | None,
        command_cb: Callable[P, T | Awaitable[T]],
    ):
        self._command_args = command_args or []
        self._command_return = command_return
        self._command_cb = command_cb
        self._last_return_value: T | None = None
        self._lock = asyncio.Lock()

        # Validate callback signature
        sig = inspect.signature(command_cb)
        params = list(sig.parameters.values())

        if len(params) != len(self._command_args):
            raise TypeError(
                f"Number of command_args ({len(self._command_args)}) does not match "
                f"callback arguments ({len(params)})"
            )

        hints = get_type_hints(command_cb)
        for i, param in enumerate(params):
            expected_type = self._command_args[i]
            actual_type = hints.get(param.name)
            if actual_type and actual_type is not expected_type:
                if not (
                    (
                        hasattr(actual_type, "__origin__")
                        and actual_type.__origin__ is expected_type
                    )
                    or actual_type == expected_type
                ):
                    raise TypeError(
                        f"command_args type {expected_type} does not match "
                        f"callback parameter '{param.name}' type {actual_type}"
                    )

        if self._command_return is not None:
            actual_return = hints.get("return")
            if actual_return and actual_return is not self._command_return:
                if (
                    get_origin(actual_return) is Awaitable
                    or get_origin(actual_return) is asyncio.Future
                ):
                    actual_return = get_args(actual_return)[0]

                if not (
                    actual_return is self._command_return
                    or actual_return == self._command_return
                ):
                    raise TypeError(
                        f"command_return type {self._command_return} does not match "
                        f"callback return type {actual_return}"
                    )

    def source(self, name: str) -> str:
        """Return the source of the command."""
        return f"softcmd://{name}"

    async def connect(self, timeout: float):
        """No-op for SoftCommandBackend."""
        pass

    async def call(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the configured callback and return its result."""
        if len(args) != len(self._command_args):
            raise TypeError(
                f"Expected {len(self._command_args)} arguments, got {len(args)}"
            )

        for i, (arg, expected_type) in enumerate(
            zip(args, self._command_args, strict=True)
        ):
            if expected_type is not None:
                origin = get_origin(expected_type) or expected_type
                if origin is Sequence:
                    if not isinstance(arg, Sequence):
                        sig = inspect.signature(self._command_cb)
                        param_name = list(sig.parameters.keys())[i]
                        raise TypeError(
                            f"Argument '{param_name}' should be {expected_type}, "
                            f"got {type(arg)}"
                        )
                elif not isinstance(arg, origin):
                    sig = inspect.signature(self._command_cb)
                    param_name = list(sig.parameters.keys())[i]
                    raise TypeError(
                        f"Argument '{param_name}' should be {expected_type}, "
                        f"got {type(arg)}"
                    )

        async with self._lock:
            result = self._command_cb(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            self._last_return_value = result
            return cast(T, result)

    def _async_lock(self):
        return self._lock


class MockCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a mock for testing."""

    def __init__(self, initial_backend: CommandBackend[P, T], mock: LazyMock):
        self._initial_backend = initial_backend
        self._mock = mock

        async_mock = AsyncMock()
        self.call_mock: Callable[P, Awaitable[T]] = cast(
            Callable[P, Awaitable[T]], async_mock
        )

        # Attach to the device mock
        self._mock().attach_mock(async_mock, "call")

    def source(self, name: str) -> str:
        """Return the source of the mocked command."""
        return f"mock+{self._initial_backend.source(name)}"

    async def connect(self, timeout: float):
        """Mock backend does not support real connection."""
        raise NotConnectedError("It is not possible to connect a MockCommandBackend")

    async def call(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the mock command."""
        return await self.call_mock(*args, **kwargs)
