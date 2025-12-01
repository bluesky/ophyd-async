"""Support for control-system Commands with typed inputs and outputs.

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

import asyncio
import collections.abc
import inspect
import typing
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from threading import Lock
from typing import (
    Any,
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
    get_args,
    get_origin,
    runtime_checkable,
)
from unittest.mock import AsyncMock

import numpy as np

from ._device import Device, DeviceConnector
from ._signal import _wait_for
from ._signal_backend import Array1D, Primitive
from ._soft_signal_backend import make_converter, make_metadata
from ._status import AsyncStatus
from ._table import Table
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    EnumTypes,
    LazyMock,
    Sequence,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
)

# ParamSpec/TypeVar to capture positional/keyword args and return type
CommandArguments = ParamSpec("CommandArguments")
CommandReturn = TypeVar("CommandReturn")

P = ParamSpec("P")
R = TypeVar("R")

CommandDatatype = (
    Primitive
    | EnumTypes
    | Array1D[np.bool_]
    | Array1D[np.int8]
    | Array1D[np.uint8]
    | Array1D[np.int16]
    | Array1D[np.uint16]
    | Array1D[np.int32]
    | Array1D[np.uint32]
    | Array1D[np.int64]
    | Array1D[np.uint64]
    | Array1D[np.float32]
    | Array1D[np.float64]
    | np.ndarray
    | Sequence[str]
    | Sequence[StrictEnum]
    | Sequence[SubsetEnum]
    | Sequence[SupersetEnum]
    | Table
)

CommandDatatypeT = TypeVar("CommandDatatypeT", bound=CommandDatatype)


def is_command_datatype(datatype: type | None) -> bool:
    if datatype is None:
        return True

    # Primitive types
    if datatype in (bool, int, float, str):
        return True

    # Enum types
    if isinstance(datatype, type) and issubclass(
        datatype, (StrictEnum, SubsetEnum, SupersetEnum)
    ):
        return True

    # NumPy arrays
    origin = get_origin(datatype)
    if datatype is np.ndarray or origin is np.ndarray:
        return True

    # Table subclasses
    if isinstance(datatype, type) and issubclass(datatype, Table):
        return True

    # Handle typed sequences (list[T], tuple[T, ...], Sequence[T])
    if origin in (list, tuple, Sequence, typing.Sequence, collections.abc.Sequence):
        args = get_args(datatype)
        if not args:  # Reject raw list/tuple (e.g., just "list" without [T])
            return False

        # Check if the inner type is a primitive or allowed enum
        inner = args[0]
        if inner in (bool, int, float, str):
            return True
        if isinstance(inner, type) and issubclass(
            inner, (StrictEnum, SubsetEnum, SupersetEnum)
        ):
            return True
        return False  # Reject sequences of non-primitives (e.g., list[SomeClass])

    # Reject raw list/tuple (e.g., `list` without type args)
    if datatype in (list, tuple):
        return False

    return False


@runtime_checkable
class CommandCallback(Protocol[CommandArguments, CommandReturn]):
    """Protocol for command callbacks that can be sync or async."""

    async def __call__(
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        pass


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
        command_args: Sequence[type[CommandDatatypeT]] | None,
        command_return: type[CommandDatatypeT] | None,
        command_cb: CommandCallback[CommandArguments, CommandReturn],
        units: str | None = None,
        precision: int | None = None,
    ):
        """Initialize the SoftCommandBackend.

        Args:
            command_args: List of expected input argument types, or a single type.
            command_return: Expected return type (or None for no return).
            command_cb: Callback implementing the command logic.
            units: Optional engineering units.
            precision: Optional numeric precision.

        Raises:
            TypeError: If argument or return types are incompatible with the callback.
        """
        if command_args is None:
            pass
        else:
            command_args = list(command_args)
            for t in command_args:
                if not is_command_datatype(t):
                    raise TypeError(f"type {t} is not a valid command_arg type")
        self.command_arg_types = command_args

        if not is_command_datatype(command_return):
            raise TypeError(f"type {command_return} is not a valid command_arg type")
        self.command_return_type = command_return

        self.callback = command_cb
        self._last_return_value: CommandReturn | None = None
        self._lock = Lock()

        if self.command_arg_types:
            self.arg_converters = [
                make_converter(t) if t is not None else None
                for t in self.command_arg_types
            ]
        else:
            self.arg_converters = []

        # If return type is None, don't create a converter
        if command_return is None:
            self.return_conv = None
        else:
            self.return_conv = make_converter(command_return)

        # Metadata should still exist even if return type is None
        self.metadata = make_metadata(command_return or float, units, precision)

        # Validate callback signature
        self._validate_callback_signature()

    def _validate_callback_signature(self) -> None:
        sig = inspect.signature(self.callback)

        # Collect explicit parameters
        explicit_params = [
            param
            for name, param in sig.parameters.items()
            if name not in ("self", "cls")
            and param.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]

        cb_param_types = [
            param.annotation if param.annotation != inspect.Parameter.empty else Any
            for param in explicit_params
        ]

        if self.command_arg_types is not None:
            # Check argument count matches
            if len(self.command_arg_types) != len(cb_param_types):
                raise TypeError(
                    f"Number of command_args "
                    f"({len(self.command_arg_types)}) doesn't match "
                    f"callback parameters ({len(cb_param_types)})"
                )

            # Check argument types match
            for i, (arg_type, cb_type) in enumerate(
                zip(self.command_arg_types, cb_param_types, strict=False)
            ):
                if cb_type is Any:
                    continue  # Skip generic Any

                origin = get_origin(cb_type) or cb_type

                # Only check subclass if both are valid classes
                if inspect.isclass(arg_type) and inspect.isclass(origin):
                    if not issubclass(arg_type, origin):
                        raise TypeError(
                            f"command_args type {arg_type} doesn't match"
                            f" callback parameter type {origin} "
                            f"at position {i}"
                        )

        # Check return type matches
        return_annotation = sig.return_annotation
        if (
            return_annotation is not inspect.Parameter.empty
            and return_annotation is not Any
        ):
            ret_origin = get_origin(return_annotation) or return_annotation
            if inspect.isclass(self.command_return_type) and inspect.isclass(
                ret_origin
            ):
                if not issubclass(self.command_return_type, ret_origin):
                    raise TypeError(
                        f"command_return type {self.command_return_type}"
                        f" doesn't match "
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
        """Convert arguments, call callback, and handle return conversion safely."""
        # Convert input arguments
        converted_args = []
        for i, arg in enumerate(args):
            if arg is None:
                converted_args.append(None)
            else:
                converter = self.arg_converters[i]
                if converter is not None:
                    converted_args.append(converter.write_value(arg))

        try:
            async with self._async_lock():
                # Call the provided callback (may be sync or async)
                result = self.callback(*converted_args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                # Only convert return if a converter exists
                if self.return_conv is not None:
                    self._last_return_value = self.return_conv.write_value(result)
                else:
                    # No converter = command has no return type
                    # (e.g. soft_command_x / w)
                    self._last_return_value = None
                return self._last_return_value

        except Exception as e:
            self._last_return_value = None
            raise ExecutionError(f"Command execution failed: {e}") from e

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
        result = self.callback(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result


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
            raise ValueError(
                "Cannot make a MockCommandBackend for a MockCommandBackend"
            )

        self.initial_backend = initial_backend
        self.mock = mock
        self._call_mock: AsyncMock | None = None
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
        self._mock_backend: MockCommandBackend | None = None

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
            f"Connecting Command backend for device "
            f"'{device.name or type(device).__name__}'"
        )
        try:
            await asyncio.wait_for(self.backend.connect(timeout), timeout=timeout)
        except TimeoutError as e:
            raise ConnectionTimeoutError(
                f"Failed to connect within {timeout} seconds"
            ) from e
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
    - Or use trigger(...) to get a Bluesky Status (return value is discarded).
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
                self._connector.backend.call(*args, **kwargs), timeout, source
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


def soft_command_r(
    command_return: type[CommandDatatypeT] | None,
    command_cb: CommandCallback[[], R],
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandR[R]:
    """Create a read-only command (no arguments, returns a value).

    Args:
        command_return: The return type of the command.
        command_cb: Callback function implementing the command logic.
        name: Optional name of the command.
        units: Optional units metadata for the command.
        precision: Optional numeric precision metadata.

    Returns:
        CommandR: A read-only command instance.

    Example:
        >>> def read_temperature() -> float:
        ...     return 22.5
        >>> cmd = soft_command_r(float, read_temperature,
         name="get_temp", units="°C", precision=1)
        >>> result = await cmd.call()
        >>> assert result == 22.5
    """
    backend = SoftCommandBackend(
        command_args=[],
        command_return=command_return,
        command_cb=command_cb,
        units=units,
        precision=precision,
    )
    return CommandR(backend, name=name)


def soft_command_w(
    command_args: Sequence[type[CommandDatatypeT]] | type[CommandDatatypeT] | None,
    command_cb: CommandCallback[CommandArguments, None],
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandW[CommandArguments]:
    """Create a write-only command (takes arguments, returns nothing).

    Args:
        command_args: A type or list of types expected as input arguments.
        command_cb: Callback function implementing the command logic.
        name: Optional name of the command.
        units: Optional units metadata for the command.
        precision: Optional numeric precision metadata.

    Returns:
        CommandW: A write-only command instance.

    Example:
        Passing a single type:
            >>> def set_value(x: int) -> None:
            ...     print(f"Value set to {x}")
            >>> cmd = soft_command_w(int, set_value, name="set_value",
             units=None)
            >>> await cmd.call(10)  # prints: Value set to 10

        Passing multiple argument types:
            >>> def set_coords(x: float, y: float) -> None:
            ...     print(f"Coords set to ({x}, {y})")
            >>> cmd = soft_command_w([float, float], set_coords,
            name="set_coords", units="mm")
            >>> await cmd.call(1.5, 2.0)
    """
    if isinstance(command_args, type):
        command_args = [command_args]
    elif command_args is None:
        command_args = []

    backend = SoftCommandBackend(
        command_args=command_args,
        command_return=None,
        command_cb=command_cb,
        units=units,
        precision=precision,
    )
    return CommandW(backend, name=name)


def soft_command_x(
    command_cb: CommandCallback[[], None],
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandX:
    """Create an executable command (no arguments, no return value).

    Args:
        command_cb: Callback function implementing the command logic.
        name: Optional name of the command.
        units: Optional units metadata for the command.
        precision: Optional numeric precision metadata.

    Returns:
        CommandX: An executable command instance.

    Example:
        >>> def run_task() -> None:
        ...     print("Task executed")
        >>> cmd = soft_command_x(run_task, name="execute")
        >>> await cmd.call()  # prints: Task executed
    """
    backend = SoftCommandBackend(
        command_args=[],
        command_return=None,
        command_cb=command_cb,
        units=units,
        precision=precision,
    )
    return CommandX(backend, name=name)


def soft_command_rw(
    command_args: Sequence[type[CommandDatatypeT]] | type[CommandDatatypeT] | None,
    command_return: type[CommandDatatypeT] | None,
    command_cb: CommandCallback[CommandArguments, R],
    name: str = "",
    units: str | None = None,
    precision: int | None = None,
) -> CommandRW[CommandArguments, R]:
    """Create a read-write command (takes arguments, returns a value).

    Args:
        command_args: A type or list of types expected as input arguments.
        command_return: The return type of the command.
        command_cb: Callback function implementing the command logic.
        name: Optional name of the command.
        units: Optional units metadata for the command.
        precision: Optional numeric precision metadata.

    Returns:
        CommandRW: A read-write command instance.

    Example:
        Passing a single input type:
            >>> def compute_square(x: int) -> int:
            ...     return x * x
            >>> cmd = soft_command_rw(int, int, compute_square,
            name="square", units=None)
            >>> result = await cmd.call(4)
            >>> assert result == 16

        Passing multiple input types:
            >>> def add(x: int, y: float) -> float:
            ...     return x + y
            >>> cmd = soft_command_rw([int, float], float, add,
            name="add", units="V", precision=2)
            >>> result = await cmd.call(3, 4.5)
            >>> assert result == 7.5
    """
    if isinstance(command_args, type):
        command_args = [command_args]
    elif command_args is None:
        command_args = []

    backend = SoftCommandBackend(
        command_args=command_args,
        command_return=command_return,
        command_cb=command_cb,
        units=units,
        precision=precision,
    )
    return CommandRW(backend, name=name)
