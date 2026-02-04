from __future__ import annotations

import asyncio
import inspect
import types
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from typing import (
    Generic,
    ParamSpec,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from unittest.mock import AsyncMock

import numpy as np

from ._device import Device, DeviceConnector, LazyMock
from ._status import AsyncStatus
from ._utils import (
    DEFAULT_TIMEOUT,
    NotConnectedError,
    T,
)


async def _wait_for(coro: Awaitable[T], timeout: float | None, source: str) -> T:
    try:
        return await asyncio.wait_for(coro, timeout)
    except TimeoutError as exc:
        raise TimeoutError(source) from exc


P = ParamSpec("P")
T_co = TypeVar("T_co", covariant=True)


class CommandBackend(Generic[P, T_co]):
    """A backend for a Command."""

    @abstractmethod
    def source(self, name: str) -> str:
        """Return source of command."""

    @abstractmethod
    async def connect(self, timeout: float) -> None:
        """Connect to underlying hardware."""

    @abstractmethod
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T_co:
        """Execute the command and return its result."""


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

    @AsyncStatus.wrap
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the command and return a status saying when it's done."""
        self.log.debug(f"Calling command {self.name}")
        result = await _wait_for(
            self._connector.backend(*args, **kwargs), self._timeout, self.source
        )
        self.log.debug(f"Command {self.name} returned {result}")
        return result


def _extract_numpy_scalar_from_dtype_annotation(
    dtype_anno: object,
) -> type[np.generic] | None:
    """Given something like np.dtype[np.float32], return np.float32."""
    origin = get_origin(dtype_anno)
    if origin is np.dtype:
        args = get_args(dtype_anno)
        if (
            len(args) == 1
            and isinstance(args[0], type)
            and issubclass(args[0], np.generic)
        ):
            return args[0]
    return None


def _check_value_against_annotation(
    value: object, annotation: object, *, path: str
) -> None:
    """Runtime-check a value against a typing annotation.

    Supports:
      - plain classes
      - unions (T1 | T2, Optional[T], Union[...])
      - Sequence[T] with element checking
      - numpy.ndarray[...] (including Array1D[np.float32]-style annotations)
    """
    # None / NoneType
    if annotation is None or annotation is type(None):  # noqa: E721
        if value is not None:
            raise TypeError(f"{path} should be {annotation}, got {type(value)}")
        return

    origin = get_origin(annotation)

    # Union support
    if origin is None and isinstance(annotation, types.UnionType):
        union_args = annotation.__args__  # type: ignore[attr-defined]
    elif origin is types.UnionType or origin is getattr(
        __import__("typing"), "Union", object()
    ):
        union_args = get_args(annotation)
    else:
        union_args = ()

    if union_args:
        last_exc: TypeError | None = None
        for opt in union_args:
            try:
                _check_value_against_annotation(value, opt, path=path)
                return
            except TypeError as exc:
                last_exc = exc
        raise TypeError(
            f"{path} should be {annotation}, got {type(value)}"
        ) from last_exc

    # Sequence[T] element checking
    if origin is Sequence:
        if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray)
        ):
            raise TypeError(f"{path} should be {annotation}, got {type(value)}")
        (elem_anno,) = get_args(annotation) or (object,)
        for i, elem in enumerate(value):
            _check_value_against_annotation(elem, elem_anno, path=f"{path}[{i}]")
        return

    # numpy.ndarray[...] including Array1D[np.float32]
    if origin is np.ndarray:
        if not isinstance(value, np.ndarray):
            raise TypeError(f"{path} should be {annotation}, got {type(value)}")

        anno_args = get_args(annotation)
        if len(anno_args) == 2:
            _shape_anno, dtype_anno = anno_args
            scalar = _extract_numpy_scalar_from_dtype_annotation(dtype_anno)
            if scalar is not None:
                expected_dtype = np.dtype(scalar)
                if value.dtype != expected_dtype:
                    raise TypeError(
                        f"{path} should be {annotation}, got ndarray dtype"
                        f" {value.dtype}"
                    )
                if value.ndim != 1:
                    raise TypeError(
                        f"{path} should be 1D array for {annotation},"
                        f" got ndim={value.ndim}"
                    )
        return

    # Parametrized non-Sequence types: check the origin only
    if origin is not None:
        if not isinstance(value, origin):
            raise TypeError(f"{path} should be {annotation}, got {type(value)}")
        return

    # Plain classes
    if isinstance(annotation, type):
        if not isinstance(value, annotation):
            raise TypeError(f"{path} should be {annotation}, got {type(value)}")
        return

    raise TypeError(f"{path} should be {annotation}, got {type(value)}")


class SoftCommandBackend(CommandBackend[P, T]):
    """A backend for a Command that uses a Python callback.

    The callback's annotations define the runtime contract.
    """

    def __init__(self, command_cb: Callable[P, T | Awaitable[T]]):
        self._command_cb = command_cb
        self._last_return_value: T | None = None
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

        inferred_return = hints["return"]
        if get_origin(inferred_return) in (Awaitable, asyncio.Future):
            inferred_return = get_args(inferred_return)[0]

        if inferred_return is None or inferred_return is type(None):
            self._command_return: type[T] | None = None
        else:
            self._command_return = cast(type[T], inferred_return)

    def source(self, name: str) -> str:
        """Return the source of the command."""
        return f"softcmd://{name}"

    async def connect(self, timeout: float):
        """No-op for SoftCommandBackend."""
        pass

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the configured callback and return its result."""
        try:
            bound = self._sig.bind(*args, **kwargs)
        except TypeError as exc:
            raise TypeError(str(exc)) from exc

        bound.apply_defaults()

        for name, value in bound.arguments.items():
            expected = self._expected_param_types[name]
            _check_value_against_annotation(value, expected, path=f"Argument '{name}'")

        async with self._lock:
            result = self._command_cb(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            self._last_return_value = cast(T, result)
            return cast(T, result)


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
        self._mock().attach_mock(async_mock, "__call__")

    def source(self, name: str) -> str:
        """Return the source of the mocked command."""
        return f"mock+{self._initial_backend.source(name)}"

    async def connect(self, timeout: float):
        """Mock backend does not support real connection."""
        raise NotConnectedError("It is not possible to connect a MockCommandBackend")

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the mock command."""
        result = await self.call_mock(*args, **kwargs)
        return cast(T, result)


def soft_command(
    command_cb: Callable[P, T | Awaitable[T]],
    name: str = "",
    timeout: float | None = DEFAULT_TIMEOUT,
) -> Command[P, T]:
    """Create a Command with a SoftCommandBackend.

    The callback must have full type annotations (all parameters + return).
    Argument and return types are inferred from those annotations.
    """
    backend: SoftCommandBackend[P, T] = SoftCommandBackend(command_cb)
    return Command(backend, timeout, name)
