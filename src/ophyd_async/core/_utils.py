from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, EnumMeta
from typing import (
    Any,
    Generic,
    Literal,
    ParamSpec,
    TypeVar,
    get_args,
    get_origin,
)
from unittest.mock import Mock

import numpy as np
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")
V = TypeVar("V")
P = ParamSpec("P")
Callback = Callable[[T], None]
DEFAULT_TIMEOUT = 10.0

logger = logging.getLogger("ophyd_async")


class UppercaseNameEnumMeta(EnumMeta):
    def __new__(cls, *args, **kwargs):
        ret = super().__new__(cls, *args, **kwargs)
        lowercase_names = [x.name for x in ret if not x.name.isupper()]  # type: ignore
        if lowercase_names:
            raise TypeError(f"Names {lowercase_names} should be uppercase")
        return ret


class AnyStringUppercaseNameEnumMeta(UppercaseNameEnumMeta):
    def __call__(self, value, *args, **kwargs):  # type: ignore
        """Return given value if it is a string and not a member of the enum.

        If the value is not a string or is an enum member, default enum behavior
        is applied. Type checking will complain if provided arbitrary string.

        Returns:
            Union[str, SubsetEnum]: If the value is a string and not a member of the
            enum, the string is returned as is. Otherwise, the corresponding enum
            member is returned.

        Raises:
            ValueError: If the value is not a string and cannot be converted to an enum
            member.

        """
        if isinstance(value, str) and not isinstance(value, self):
            return value
        return super().__call__(value, *args, **kwargs)


class StrictEnum(str, Enum, metaclass=UppercaseNameEnumMeta):
    """All members should exist in the Backend, and there will be no extras."""


class SubsetEnum(str, Enum, metaclass=AnyStringUppercaseNameEnumMeta):
    """All members should exist in the Backend, but there may be extras."""


class SupersetEnum(str, Enum, metaclass=UppercaseNameEnumMeta):
    """Some members should exist in the Backend, and there should be no extras."""


EnumTypes = StrictEnum | SubsetEnum | SupersetEnum


CALCULATE_TIMEOUT = "CALCULATE_TIMEOUT"
"""Sentinel used to implement ``myfunc(timeout=CalculateTimeout)``

This signifies that the function should calculate a suitable non-zero
timeout itself
"""


CalculatableTimeout = float | None | Literal["CALCULATE_TIMEOUT"]


class NotConnected(Exception):
    """Exception to be raised if a `Device.connect` is cancelled.

    :param errors:
        Mapping of device name to Exception or another NotConnected.
        Alternatively a string with the signal error text.
    """

    _indent_width = "    "

    def __init__(self, errors: str | Mapping[str, Exception]):
        self._errors = errors

    @property
    def sub_errors(self) -> Mapping[str, Exception]:
        if isinstance(self._errors, dict):
            return self._errors.copy()
        else:
            return {}

    def _format_sub_errors(self, name: str, error: Exception, indent="") -> str:
        if isinstance(error, NotConnected):
            error_txt = ":" + error.format_error_string(indent + self._indent_width)
        elif isinstance(error, Exception):
            error_txt = ": " + err_str + "\n" if (err_str := str(error)) else "\n"
        else:
            raise RuntimeError(
                f"Unexpected type `{type(error)}`, expected an Exception"
            )

        string = f"{indent}{name}: {type(error).__name__}" + error_txt
        return string

    def format_error_string(self, indent="") -> str:
        if not isinstance(self._errors, dict) and not isinstance(self._errors, str):
            raise RuntimeError(
                f"Unexpected type `{type(self._errors)}` expected `str` or `dict`"
            )

        if isinstance(self._errors, str):
            return " " + self._errors + "\n"

        string = "\n"
        for name, error in self._errors.items():
            string += self._format_sub_errors(name, error, indent=indent)
        return string

    def __str__(self) -> str:
        return self.format_error_string(indent="")

    @classmethod
    def with_other_exceptions_logged(
        cls, exceptions: Mapping[str, Exception]
    ) -> NotConnected:
        for name, exception in exceptions.items():
            if not isinstance(exception, NotConnected):
                logger.exception(
                    f"device `{name}` raised unexpected exception "
                    f"{type(exception).__name__}",
                    exc_info=exception,
                )
        return NotConnected(exceptions)


@dataclass(frozen=True)
class WatcherUpdate(Generic[T]):
    """A dataclass such that, when expanded, it provides the kwargs for a watcher."""

    current: T
    """The current value, where it currently is."""

    initial: T
    """The initial value, where it was when it started."""

    target: T
    """The target value, where it will be when it finishes."""

    name: str | None = None
    """An optional name for the device, if available."""

    unit: str | None = None
    """Units of the value, if applicable."""

    precision: float | None = None
    """How many decimal places the value should be displayed to."""

    fraction: float | None = None
    """The fraction of the way between initial and target."""

    time_elapsed: float | None = None
    """The time elapsed since the start of the operation."""

    time_remaining: float | None = None
    """The time remaining until the operation completes."""


async def wait_for_connection(**coros: Awaitable[None]):
    """Call many underlying signals, accumulating exceptions and returning them.

    Expected kwargs should be a mapping of names to coroutine tasks to execute.
    """
    exceptions: dict[str, Exception] = {}
    if len(coros) == 1:
        # Single device optimization
        name, coro = coros.popitem()
        try:
            await coro
        except Exception as e:
            exceptions[name] = e
    else:
        # Use gather to connect in parallel
        results = await asyncio.gather(*coros.values(), return_exceptions=True)
        for name, result in zip(coros, results, strict=False):
            if isinstance(result, Exception):
                exceptions[name] = result

    if exceptions:
        raise NotConnected.with_other_exceptions_logged(exceptions)


def get_dtype(datatype: type) -> np.dtype:
    """Get the runtime dtype from a numpy ndarray type annotation.

    ```python
    >>> from ophyd_async.core import Array1D
    >>> import numpy as np
    >>> get_dtype(Array1D[np.int8])
    dtype('int8')

    ```
    """
    if not get_origin(datatype) == np.ndarray:
        raise TypeError(f"Expected Array1D[dtype], got {datatype}")
    # datatype = numpy.ndarray[typing.Any, numpy.dtype[numpy.float64]]
    # so extract numpy.float64 from it
    return np.dtype(get_args(get_args(datatype)[1])[0])


def get_enum_cls(datatype: type | None) -> type[EnumTypes] | None:
    """Get the enum class from a datatype.

    :raises TypeError: if type is not a [](#StrictEnum) or [](#SubsetEnum)
    or [](#SupersetEnum) subclass
    ```python
    >>> from ophyd_async.core import StrictEnum
    >>> from collections.abc import Sequence
    >>> class MyEnum(StrictEnum):
    ...     A = "A value"
    >>> get_enum_cls(str)
    >>> get_enum_cls(MyEnum)
    <enum 'MyEnum'>
    >>> get_enum_cls(Sequence[MyEnum])
    <enum 'MyEnum'>

    ```
    """
    if get_origin(datatype) is Sequence:
        datatype = get_args(datatype)[0]
    if datatype and issubclass(datatype, Enum):
        if not issubclass(datatype, EnumTypes):
            raise TypeError(
                f"{datatype} should inherit from ophyd_async.core.SubsetEnum "
                "or ophyd_async.core.StrictEnum "
                "or ophyd_async.core.SupersetEnum."
            )
        return datatype
    return None


def get_unique(values: dict[str, T], types: str) -> T:
    """If all values are the same, return that value, otherwise raise TypeError.

    ```python
    >>> get_unique({"a": 1, "b": 1}, "integers")
    1
    >>> get_unique({"a": 1, "b": 2}, "integers")
    Traceback (most recent call last):
     ...
    TypeError: Differing integers: a has 1, b has 2

    ```
    """
    set_values = set(values.values())
    if len(set_values) != 1:
        diffs = ", ".join(f"{k} has {v}" for k, v in values.items())
        raise TypeError(f"Differing {types}: {diffs}")
    return set_values.pop()


async def merge_gathered_dicts(
    coros: Iterable[Awaitable[dict[str, T]]],
) -> dict[str, T]:
    """Merge dictionaries produced by a sequence of coroutines.

    Can be used for merging `read()` or `describe()`.

    :example:
    ```python
    combined_read = await merge_gathered_dicts(s.read() for s in signals)
    ```
    """
    ret: dict[str, T] = {}
    for result in await asyncio.gather(*coros):
        ret.update(result)
    return ret


async def gather_dict(coros: Mapping[T, Awaitable[V]]) -> dict[T, V]:
    """Take named coros and return a dict of their name to their return value."""
    values = await asyncio.gather(*coros.values())
    return dict(zip(coros, values, strict=True))


def in_micros(t: float) -> int:
    """Convert between a seconds and microseconds.

    :param t: A time in seconds
    :return: A time in microseconds, rounded up to the nearest whole microsecond
    :raises ValueError: if t < 0
    """
    if t < 0:
        raise ValueError(f"Expected a positive time in seconds, got {t!r}")
    return int(np.ceil(t * 1e6))


def get_origin_class(annotatation: Any) -> type | None:
    origin = get_origin(annotatation) or annotatation
    if isinstance(origin, type):
        return origin
    return None


class Reference(Generic[T]):
    """Hide an object behind a reference.

    Used to opt out of the naming/parent-child relationship of `Device`.

    :example:
    ```python
    class DeviceWithRefToSignal(Device):
        def __init__(self, signal: SignalRW[int]):
            self.signal_ref = Reference(signal)
            super().__init__()

        def set(self, value) -> AsyncStatus:
            return self.signal_ref().set(value + 1)
    ```
    """

    def __init__(self, obj: T):
        self._obj = obj

    def __call__(self) -> T:
        return self._obj


class LazyMock:
    """A lazily created Mock to be used when connecting in mock mode.

    Creating Mocks is reasonably expensive when each Device (and Signal)
    requires its own, and the tree is only used when ``Signal.set()`` is
    called. This class allows a tree of lazily connected Mocks to be
    constructed so that when the leaf is created, so are its parents.
    Any calls to the child are then accessible from the parent mock.

    ```python
    >>> parent = LazyMock()
    >>> child = parent.child("child")
    >>> child_mock = child()
    >>> child_mock()  # doctest: +ELLIPSIS
    <Mock name='mock.child()' id='...'>
    >>> parent_mock = parent()
    >>> parent_mock.mock_calls
    [call.child()]

    ```
    """

    def __init__(self, name: str = "", parent: LazyMock | None = None) -> None:
        self.parent = parent
        self.name = name
        self._mock: Mock | None = None

    def child(self, name: str) -> LazyMock:
        """Return a child of this LazyMock with the given name."""
        return LazyMock(name, self)

    def __call__(self) -> Mock:
        if self._mock is None:
            self._mock = Mock(spec=object)
            if self.parent is not None:
                self.parent().attach_mock(self._mock, self.name)
        return self._mock


class ConfinedModel(BaseModel):
    """A base class confined to explicitly defined fields in the model schema."""

    model_config = ConfigDict(
        extra="forbid",
    )


def error_if_none(value: T | None, msg: str) -> T:
    """Check and return the value if not None.

    :param value: The value to check
    :param msg: The `RuntimeError` message to raise if it is None
    :raises RuntimeError: If the value is None
    :returns: The value if not None

    Used to implement a pattern where a variable is None at init, then
    changed by a method, then used in a later method.
    """
    if value is None:
        raise RuntimeError(msg)
    return value
