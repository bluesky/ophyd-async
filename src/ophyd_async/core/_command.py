"""
Support for control-system Commands with typed inputs and outputs.

Background:
- In Tango, commands may take an input and/or produce an output, and the
  input/output types do not have to match. Historically we represented such
  commands by bending Signal types (e.g. using SignalX or treating a command
  as a SignalR/W/RW), which led to awkward patterns like having to "read" a
  motor's Stop command.

Solution:
- Provide a dedicated Command device and backend interface that models a
  call with typed arguments and a typed return value.
- Provide a connector for Device.connect() integration, including mock mode.
- Provide a MockCommandBackend for tests and offline use.
"""
from __future__ import annotations

from ._signal_backend import make_datakey
import time
import asyncio
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any, Generic, ParamSpec, TypeVar
from collections.abc import Awaitable, Callable
from event_model import DataKey

from ._device import Device, DeviceConnector
from ._status import AsyncStatus
from ._utils import LazyMock, CalculatableTimeout, CALCULATE_TIMEOUT
from ._signal import _wait_for

# ParamSpec/TypeVar to capture positional/keyword args and return type
CommandArguments = ParamSpec("CommandArguments")
CommandReturn = TypeVar("CommandReturn")

# Local generics for helper factories so callers can specify argument and return types
P = ParamSpec("P")
R = TypeVar("R")


class _ChildrenNotAllowed(dict[str, Device]):
    def __setitem__(self, key: str, value: Device) -> None:
        raise KeyError(
            f"Cannot add Device or Signal child {key}={value} of Command, "
            "make a subclass of Device instead"
        )


class CommandBackend(Generic[CommandArguments, CommandReturn], ABC):
    """Abstract backend interface for a Command.

    Backends implement connection and the actual command invocation.
    """

    @abstractmethod
    def source(self, name: str, read: bool) -> str:
        """Return source of signal.

        :param name: The name of the signal, which can be used or discarded.
        :param read: True if we want the source for reading, False if writing.
        """

    @abstractmethod
    async def get_datakey(self, source: str) -> DataKey:
        """Metadata like source, dtype, shape, precision, units."""

    @abstractmethod
    async def connect(self, timeout: float) -> None:
        """Connect to underlying hardware."""

    @abstractmethod
    async def call(
        self, *args: CommandArguments.args, wait: bool, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        """Invoke the command and return its result (if any)."""

class SoftCommandBackend(CommandBackend[CommandArguments, CommandReturn]):
    """A soft/in-memory backend for Commands without a custom implementation.

    This backend returns a preset return value regardless of the input args.
    Units and precision are stored as metadata for describe purposes.
    """

    def __init__(
        self,
        command_args: Generic[CommandArguments],
        command_return: CommandReturn,
        units: str | None = None,
        precision: int | None = None,
    ):
        # command_args is kept for symmetry/typing hints but unused at runtime
        self._return_value: CommandReturn = command_return
        self._units = units
        self._precision = precision

    def set_return_value(self, value: CommandReturn) -> None:
        """Set the value that future calls will return."""
        self._return_value = value

    def source(self, name: str, read: bool) -> str:
        # read flag is irrelevant for commands; retain signature for parity
        return f"softcmd://{name}"

    async def connect(self, timeout: float) -> None:
        # No external resources to connect
        return None

    async def call(
        self, *args: CommandArguments.args, wait: bool, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        # Ignore args and return the preset value
        return self._return_value

    async def get_datakey(self, source: str) -> DataKey:
        # Best-effort DataKey using current return value as exemplar
        metadata: dict[str, Any] = {}
        if self._units is not None:
            metadata["units"] = self._units
        if self._precision is not None:
            metadata["precision"] = self._precision
        dtype = type(self._return_value) if self._return_value is not None else object
        return make_datakey(dtype, self._return_value, source, metadata)


class MockCommandBackend(CommandBackend[CommandArguments, CommandReturn]):
    """Command backend for testing, created by ``Device.connect(mock=True)``.

    Tracks calls via an AsyncMock and blocks completion on an Event, while
    returning a configurable value via an internal SoftCommandBackend.
    """

    def __init__(
        self,
        initial_backend: CommandBackend[CommandArguments, CommandReturn],
        mock: LazyMock,
    ) -> None:
        if isinstance(initial_backend, MockCommandBackend):
            raise ValueError("Cannot make a MockCommandBackend for a MockCommandBackend")
        self.initial_backend = initial_backend
        # Internal soft backend to hold configurable return value/metadata
        self.soft_backend = SoftCommandBackend(command_args=(), command_return=None)
        self.mock = mock

    @cached_property
    def call_mock(self) -> Any:
        from unittest.mock import AsyncMock

        cm = AsyncMock(name="call")
        self.mock().attach_mock(cm, "call")
        return cm

    @cached_property
    def proceeds(self) -> asyncio.Event:
        ev = asyncio.Event()
        ev.set()
        return ev

    def set_return_value(self, value: CommandReturn) -> None:
        self.soft_backend.set_return_value(value)

    def source(self, name: str, read: bool) -> str:
        return f"mock+{self.initial_backend.source(name, read)}"

    async def connect(self, timeout: float) -> None:
        raise RuntimeError("It is not possible to connect a MockCommandBackend")

    async def get_datakey(self, source: str) -> DataKey:
        return await self.soft_backend.get_datakey(source)

    async def call(
        self, *args: CommandArguments.args, wait: bool, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        # Record the call and delegate the return value to the soft backend
        await self.call_mock(*args, wait=wait, **kwargs)
        result = await self.soft_backend.call(*args, wait=wait, **kwargs)
        if wait:
            await self.proceeds.wait()
        return result


class CommandConnector(DeviceConnector):
    """Used for connecting Command devices with a given backend."""

    def __init__(self, backend: CommandBackend):
        self.backend = self._init_backend = backend

    async def connect_mock(self, device: Device, mock: LazyMock):
        # Swap in a mock backend that does not touch real hardware
        self.backend = MockCommandBackend(self._init_backend, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        # Use the real backend and connect it
        self.backend = self._init_backend
        device.log.debug(
            f"Connecting Command backend for device '{device.name or type(device).__name__}'"
        )
        await self.backend.connect(timeout)


class Command(Device, Generic[CommandArguments, CommandReturn]):
    """A Device representing an invokable command.

    - Call the command directly with await command.call(...)
    - Or use trigger(...) to get a Bluesky Status (return value is discarded)
    """

    _connector: CommandConnector
    _child_devices = _ChildrenNotAllowed()  # type: ignore

    def __init__(
        self,
        backend: CommandBackend[CommandArguments, CommandReturn],
        name: str = "",
    ) -> None:
        super().__init__(name=name, connector=CommandConnector(backend))

    async def call(
        self, *args: CommandArguments.args, wait: bool = True, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        """Invoke the underlying command and return its result (if any)."""
        return await self._connector.backend.call(*args, wait=wait, **kwargs)

    @AsyncStatus.wrap
    async def trigger(
        self,
        *args: CommandArguments.args,
        wait=True,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
        **kwargs: CommandArguments.kwargs,
    ) -> None:
        """Invoke the command, returning a Status representing completion.

        Note: Any return value from the backend is ignored. Use call() if you
        need the returned value.
        """
        # Commands don't have a built-in timeout attribute; if asked to calculate,
        # default to no timeout (let the backend decide or rely on caller's await).
        if timeout == CALCULATE_TIMEOUT:
            timeout = None
        source = self._connector.backend.source(self.name, read=False)
        self.log.debug(f"Calling command backend at source {source}")
        # Forward only the command arguments; 'wait' is a bluesky concept not
        # understood by CommandBackend.call(). The 'wait' flag is kept for API
        # parity with Signal.trigger but unused here.
        await _wait_for(self._connector.backend.call(*args, wait=wait, **kwargs), timeout, source)
        self.log.debug(f"Successfully completed command at source {source}")


class CommandR(Command[[], CommandReturn], Generic[CommandReturn]):
    """Read-only command: takes no input, returns a value."""


class CommandW(Command[CommandArguments, None], Generic[CommandArguments]):
    """Write-only command: takes input arguments, returns nothing (None)."""


class CommandRW(
    Command[CommandArguments, CommandReturn], Generic[CommandArguments, CommandReturn]
):
    """Read-write command: takes input arguments and returns a value."""


class CommandX(Command[[], None]):
    """Executable command: takes no input and returns nothing (None)."""


def _default_of(datatype: type | None) -> Any:
    try:
        return datatype() if datatype is not None else None
    except Exception:
        return None


def soft_command_r(
    command_return: R,
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandR[R]:
    """Create a read-only Command (no args, returns a value) with a SoftCommandBackend."""
    backend = SoftCommandBackend[[], R]([], command_return, units, precision)  # type: ignore[list-item]
    return CommandR(backend, name=name)


def soft_command_w(
    command_args: Generic[P],
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandW[CommandArguments]:
    """Create a write-only Command (args, no return) with a SoftCommandBackend."""
    backend = SoftCommandBackend[CommandArguments, None](command_args, None, units, precision)
    return CommandW(backend, name=name)


def soft_command_x(
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandX:
    """Create an executable Command (no args, no return) with a SoftCommandBackend."""
    backend = SoftCommandBackend[[], None]([], None, units, precision)  # type: ignore[list-item]
    return CommandX(backend, name=name)


def soft_command_rw(
        command_args: Generic[P],
        command_return: R,
        name: str = "",
        units: str | None = None,
        precision: int | None = None,
) -> CommandRW[P, R]:
    """Create a read-write Command with a SoftCommandBackend.

    Typing:
    - `P` captures the argument types for the command's arguments.
    - `R` is the declared return type.
    """
    backend = SoftCommandBackend[P, R](command_args, command_return, units, precision)
    return CommandRW(backend, name=name)
