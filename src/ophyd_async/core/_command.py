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
import inspect
import numpy as np
from unittest.mock import AsyncMock
from functools import cached_property
from typing import (
    Any, Generic, ParamSpec, TypeVar, Dict, Type, Optional, Sequence,
    Union, Tuple, Callable, Awaitable, cast, get_type_hints, get_origin,
    get_args, Protocol, runtime_checkable
)
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from threading import Lock
from event_model import DataKey
from ._device import Device, DeviceConnector
from ._status import AsyncStatus
from ._utils import LazyMock, CalculatableTimeout, CALCULATE_TIMEOUT
from ._signal import _wait_for
from ._signal_backend import Array1D

# ParamSpec/TypeVar to capture positional/keyword args and return type
CommandArguments = ParamSpec("CommandArguments")
CommandReturn = TypeVar("CommandReturn")

P = ParamSpec("P")
R = TypeVar("R")

@runtime_checkable
class CommandCallback(Protocol[CommandArguments, CommandReturn]):
    """Protocol for command callbacks that can be sync or async."""
    async def __call__(self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs) -> CommandReturn: ...

class CommandError(Exception):
    """Base class for command-related errors."""
    pass

class ConnectionError(CommandError):
    """Command connection failed."""
    pass

class ConnectionTimeoutError(ConnectionError):
    """Command connection timed out."""
    pass

class ExecutionError(CommandError):
    """Command execution failed."""
    pass

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
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        """Invoke the command and return its result (if any)."""

class SoftCommandBackend(CommandBackend[CommandArguments, CommandReturn]):
    """A soft/in-memory backend for Commands with a custom callback implementation.
    This backend executes the provided callback function when the command is called.
    Units and precision are stored as metadata for describe purposes.
    """
    def __init__(
        self,
        command_args: Sequence[Type[Any]],
        command_return: Type[CommandReturn],
        command_cb: CommandCallback[CommandArguments, CommandReturn],
        units: str | None= None,
        precision: int | None = None,
    ):
        """
        Initialize the SoftCommandBackend.

        Args:
            command_args: List of expected input argument types
            command_return: Expected return type
            command_cb: Callback function that implements the command logic
            units: Optional units for the command
            precision: Optional precision for the command

        Raises:
            TypeError: If argument types don't match callback parameter annotations
        """
        self._command_args = command_args
        self._command_return_type = command_return
        self._command_cb = command_cb
        self._units = units
        self._precision = precision
        self._last_return_value: Optional[CommandReturn] = None
        self._lock = Lock()

        # Validate callback signature
        self._validate_callback_signature()

    def _validate_callback_signature(self) -> None:
        """Validate that command_args and command_return match the callback signature."""
        sig = inspect.signature(self._command_cb)

        # Collect explicit parameters
        explicit_params = [
            param for name, param in sig.parameters.items()
            if name not in ('self', 'cls')
               and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]

        cb_param_types = [
            param.annotation if param.annotation != inspect.Parameter.empty else Any
            for param in explicit_params
        ]

        # Check argument count matches
        if len(self._command_args) != len(cb_param_types):
            raise TypeError(
                f"Number of command_args ({len(self._command_args)}) doesn't match "
                f"callback parameters ({len(cb_param_types)})"
            )

        # Check argument types match
        for i, (arg_type, cb_type) in enumerate(zip(self._command_args, cb_param_types)):
            if cb_type is Any:
                continue  # Skip generic Any

            origin = get_origin(cb_type) or cb_type

            # Only check subclass if both are valid classes
            if inspect.isclass(arg_type) and inspect.isclass(origin):
                if not issubclass(arg_type, origin):
                    raise TypeError(
                        f"command_args type {arg_type} doesn't match callback parameter type {origin} "
                        f"at position {i}"
                    )

        # Check return type matches
        return_annotation = sig.return_annotation
        if return_annotation is not inspect.Parameter.empty and return_annotation is not Any:
            ret_origin = get_origin(return_annotation) or return_annotation
            if inspect.isclass(self._command_return_type) and inspect.isclass(ret_origin):
                if not issubclass(self._command_return_type, ret_origin):
                    raise TypeError(
                        f"command_return type {self._command_return_type} doesn't match "
                        f"callback return annotation {return_annotation}"
                    )

    def source(self, name: str, read: bool) -> str:
        # read flag is irrelevant for commands; retain signature for parity
        return f"softcmd://{name}"

    async def connect(self, timeout: float) -> None:
        # No external resources to connect
        return None

    async def call(
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        """
        Invoke the command callback and return its result.

        Args:
            *args: Positional arguments to pass to the command
            **kwargs: Keyword arguments to pass to the command

        Returns:
            The result of the command callback

        Raises:
            ExecutionError: If the command execution fails
        """
        try:
            async with self._async_lock():
                result = await self._call_callback(*args, **kwargs)
                self._last_return_value = result
                return result
        except Exception as e:
            self._last_return_value = None
            raise ExecutionError(f"Command execution failed: {str(e)}") from e

    @asynccontextmanager
    async def _async_lock(self):
        """Async context manager for thread safety."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        try:
            yield
        finally:
            loop.run_in_executor(None, self._lock.release)

    async def _call_callback(self, *args, **kwargs):
        """Call the command callback, handling both sync and async callbacks."""
        result = self._command_cb(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def get_datakey(self, source: str) -> DataKey:
        metadata: dict[str, any] = {}
        if self._units is not None:
            metadata["units"] = self._units
        if self._precision is not None:
            metadata["precision"] = self._precision

        dtype = self._command_return_type or object
        exemplar = None

        if self._last_return_value is not None:
            exemplar = self._last_return_value
            actual_type = type(exemplar)
            dtype_origin = get_origin(dtype) or dtype
            if inspect.isclass(actual_type) and inspect.isclass(dtype_origin):
                if issubclass(actual_type, dtype_origin):
                    dtype = actual_type

            # For generic sequences (lists/tuples), do not pass the list itself
            if isinstance(exemplar, Sequence) and not isinstance(exemplar, (str, bytes, np.ndarray)):
                exemplar = None  # <--- key change

        return make_datakey(dtype, exemplar, source, metadata)

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
        self.mock = mock
        self._call_mock: Optional[AsyncMock] = None
        self._proceeds = asyncio.Event()
        self._proceeds.set()
        self._return_value = None

    @property
    def call_mock(self) -> AsyncMock:
        """Lazy-initialized mock for command calls."""
        if self._call_mock is None:
            cm = AsyncMock(name="call")
            self.mock().attach_mock(cm, "call")
            self._call_mock = cm
        return self._call_mock

    @property
    def proceeds(self) -> asyncio.Event:
        """Event to control when the command proceeds."""
        return self._proceeds

    def source(self, name: str, read: bool) -> str:
        return f"mock+{self.initial_backend.source(name, read)}"

    async def connect(self, timeout: float) -> None:
        raise ConnectionError("It is not possible to connect a MockCommandBackend")

    async def get_datakey(self, source: str) -> DataKey:
        return await self.initial_backend.get_datakey(source)

    async def call(
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        # Record the call and delegate the return value to the soft backend
        await self.call_mock(*args, **kwargs)
        result = await self.initial_backend.call(*args, **kwargs)
        await self.proceeds.wait()
        return result

class CommandConnector(DeviceConnector):
    """Used for connecting Command devices with a given backend."""
    def __init__(self, backend: CommandBackend):
        self.backend = self._init_backend = backend
        self._mock_backend: Optional[MockCommandBackend] = None

    async def connect_mock(self, device: Device, mock: LazyMock):
        """Swap in a mock backend that does not touch real hardware."""
        if not isinstance(self.backend, MockCommandBackend):
            self._mock_backend = MockCommandBackend(self._init_backend, mock)
            self.backend = self._mock_backend

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        """Use the real backend and connect it."""
        if isinstance(self.backend, MockCommandBackend):
            if self._mock_backend:
                self._mock_backend.cleanup()
            self.backend = self._init_backend

        device.log.debug(
            f"Connecting Command backend for device '{device.name or type(device).__name__}'"
        )
        try:
            await asyncio.wait_for(self.backend.connect(timeout), timeout=timeout)
        except asyncio.TimeoutError:
            raise ConnectionTimeoutError(f"Failed to connect within {timeout} seconds")
        except Exception as e:
            raise ConnectionError(f"Connection failed: {str(e)}") from e

    def cleanup(self) -> None:
        """Clean up any mock resources."""
        if self._mock_backend:
            self._mock_backend.cleanup()
            self._mock_backend = None

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
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        """Invoke the underlying command and return its result (if any)."""
        return await self._connector.backend.call(*args, **kwargs)

    @AsyncStatus.wrap
    async def trigger(
        self,
        *args: CommandArguments.args,
        wait: bool = True,
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

        try:
            # Forward only the command arguments
            await _wait_for(
                self._connector.backend.call(*args, **kwargs),
                timeout,
                source
            )
            self.log.debug(f"Successfully completed command at source {source}")
        except Exception as e:
            self.log.error(f"Command failed at source {source}: {str(e)}")
            raise

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

def _default_of(datatype: Optional[type]) -> Any:
    """Get a default value for a type."""
    if datatype is None:
        return None
    try:
        if datatype is bool:
            return False
        if datatype in (int, float, complex):
            return 0
        if datatype is str:
            return ""
        return datatype()
    except Exception:
        return None

def soft_command_r(
    command_return: Type[R],
    command_cb: CommandCallback[[], R],
    name: str = "",
    units: Optional[str] = None,
    precision: Optional[int] = None,
) -> CommandR[R]:
    """Create a read-only Command (no args, returns a value) with a SoftCommandBackend.

    Args:
        command_return: The return type of the command
        command_cb: Callback function that implements the command logic
        name: Name of the command
        units: Optional units for the command
        precision: Optional precision for the command

    Returns:
        A read-only Command instance
    """
    if not isinstance(command_return, type):
        raise TypeError("command_return must be a type object")

    backend = SoftCommandBackend[
        Tuple[()],  # Empty tuple for no arguments
        R
    ](
        command_args=[],
        command_return=command_return,
        command_cb=command_cb,
        units=units,
        precision=precision
    )
    return CommandR[R](backend, name=name)

def soft_command_w(
    *command_args: Type[Any],
    command_cb: CommandCallback[CommandArguments, None],
    name: str = "",
    units: Optional[str] = None,
    precision: Optional[int] = None,
) -> CommandW[CommandArguments]:
    """Create a write-only Command (args, no return) with a SoftCommandBackend.

    Args:
        *command_args: Expected input argument types
        command_cb: Callback function that implements the command logic
        name: Name of the command
        units: Optional units for the command
        precision: Optional precision for the command

    Returns:
        A write-only Command instance
    """
    backend = SoftCommandBackend[
        CommandArguments,
        None
    ](
        command_args=list(command_args),
        command_return=None,
        command_cb=command_cb,
        units=units,
        precision=precision
    )
    return CommandW[CommandArguments](backend, name=name)

def soft_command_x(
    command_cb: CommandCallback[[], None],
    name: str = "",
    units: Optional[str] = None,
    precision: Optional[int] = None,
) -> CommandX:
    """Create an executable Command (no args, no return) with a SoftCommandBackend.

    Args:
        command_cb: Callback function that implements the command logic
        name: Name of the command
        units: Optional units for the command
        precision: Optional precision for the command

    Returns:
        An executable Command instance
    """
    backend = SoftCommandBackend[
        Tuple[()],  # Empty tuple for no arguments
        None
    ](
        command_args=[],
        command_return=None,
        command_cb=command_cb,
        units=units,
        precision=precision
    )
    return CommandX(backend, name=name)

def soft_command_rw(
    *command_args: Type[Any],
    command_return: Type[R],
    command_cb: CommandCallback[CommandArguments, R],
    name: str = "",
    units: Optional[str] = None,
    precision: Optional[int] = None,
) -> CommandRW[CommandArguments, R]:
    """Create a read-write Command with a SoftCommandBackend.

    Args:
        *command_args: Expected input argument types
        command_return: The return type of the command
        command_cb: Callback function that implements the command logic
        name: Name of the command
        units: Optional units for the command
        precision: Optional precision for the command

    Returns:
        A read-write Command instance
    """
    if not isinstance(command_return, type):
        raise TypeError("command_return must be a type object")

    backend = SoftCommandBackend[
        CommandArguments,
        R
    ](
        command_args=list(command_args),
        command_return=command_return,
        command_cb=command_cb,
        units=units,
        precision=precision
    )
    return CommandRW[CommandArguments, R](backend, name=name)