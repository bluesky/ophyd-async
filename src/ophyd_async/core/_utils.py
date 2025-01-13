from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, EnumMeta
from typing import Any, Generic, Literal, ParamSpec, TypeVar, get_args, get_origin
from unittest.mock import Mock

import numpy as np

T = TypeVar("T")
P = ParamSpec("P")
Callback = Callable[[T], None]
DEFAULT_TIMEOUT = 10.0
ErrorText = str | Mapping[str, Exception]


class StrictEnumMeta(EnumMeta):
    def __new__(metacls, *args, **kwargs):
        ret = super().__new__(metacls, *args, **kwargs)
        lowercase_names = [x.name for x in ret if not x.name.isupper()]  # type: ignore
        if lowercase_names:
            raise TypeError(f"Names {lowercase_names} should be uppercase")
        return ret


class StrictEnum(str, Enum, metaclass=StrictEnumMeta):
    """All members should exist in the Backend, and there will be no extras"""


class SubsetEnumMeta(StrictEnumMeta):
    def __call__(self, value, *args, **kwargs):  # type: ignore
        if isinstance(value, str) and not isinstance(value, self):
            return value
        return super().__call__(value, *args, **kwargs)


class SubsetEnum(StrictEnum, metaclass=SubsetEnumMeta):
    """All members should exist in the Backend, but there may be extras"""


CALCULATE_TIMEOUT = "CALCULATE_TIMEOUT"
"""Sentinel used to implement ``myfunc(timeout=CalculateTimeout)``

This signifies that the function should calculate a suitable non-zero
timeout itself
"""


CalculatableTimeout = float | None | Literal["CALCULATE_TIMEOUT"]


class NotConnected(Exception):
    """Exception to be raised if a `Device.connect` is cancelled"""

    _indent_width = "    "

    def __init__(self, errors: ErrorText):
        """
        NotConnected holds a mapping of device/signal names to
        errors.

        Parameters
        ----------
        errors: ErrorText
            Mapping of device name to Exception or another NotConnected.
            Alternatively a string with the signal error text.
        """

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
                logging.exception(
                    f"device `{name}` raised unexpected exception "
                    f"{type(exception).__name__}",
                    exc_info=exception,
                )
        return NotConnected(exceptions)


@dataclass(frozen=True)
class WatcherUpdate(Generic[T]):
    """A dataclass such that, when expanded, it provides the kwargs for a watcher"""

    current: T
    initial: T
    target: T
    name: str | None = None
    unit: str | None = None
    precision: float | None = None
    fraction: float | None = None
    time_elapsed: float | None = None
    time_remaining: float | None = None


async def wait_for_connection(**coros: Awaitable[None]):
    """Call many underlying signals, accumulating exceptions and returning them

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
    """Get the runtime dtype from a numpy ndarray type annotation

    >>> from ophyd_async.core import Array1D
    >>> import numpy as np
    >>> get_dtype(Array1D[np.int8])
    dtype('int8')
    """
    if not get_origin(datatype) == np.ndarray:
        raise TypeError(f"Expected Array1D[dtype], got {datatype}")
    # datatype = numpy.ndarray[typing.Any, numpy.dtype[numpy.float64]]
    # so extract numpy.float64 from it
    return np.dtype(get_args(get_args(datatype)[1])[0])


def get_enum_cls(datatype: type | None) -> type[StrictEnum] | None:
    """Get the runtime dtype from a numpy ndarray type annotation

    >>> import numpy.typing as npt
    >>> import numpy as np
    >>> get_dtype(npt.NDArray[np.int8])
    dtype('int8')
    """
    if get_origin(datatype) is Sequence:
        datatype = get_args(datatype)[0]
    if datatype and issubclass(datatype, Enum):
        if not issubclass(datatype, StrictEnum):
            raise TypeError(
                f"{datatype} should inherit from ophyd_async.core.SubsetEnum "
                "or ophyd_async.core.StrictEnum"
            )
        return datatype


def get_unique(values: dict[str, T], types: str) -> T:
    """If all values are the same, return that value, otherwise raise TypeError

    >>> get_unique({"a": 1, "b": 1}, "integers")
    1
    >>> get_unique({"a": 1, "b": 2}, "integers")
    Traceback (most recent call last):
     ...
    TypeError: Differing integers: a has 1, b has 2
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

    Can be used for merging ``read()`` or ``describe``. For instance::

        combined_read = await merge_gathered_dicts(s.read() for s in signals)
    """
    ret: dict[str, T] = {}
    for result in await asyncio.gather(*coros):
        ret.update(result)
    return ret


async def gather_list(coros: Iterable[Awaitable[T]]) -> list[T]:
    return await asyncio.gather(*coros)


def in_micros(t: float) -> int:
    """
    Converts between a positive number of seconds and an equivalent
    number of microseconds.

    Args:
        t (float): A time in seconds
    Raises:
        ValueError: if t < 0
    Returns:
        t (int): A time in microseconds, rounded up to the nearest whole microsecond,
    """
    if t < 0:
        raise ValueError(f"Expected a positive time in seconds, got {t!r}")
    return int(np.ceil(t * 1e6))


def get_origin_class(annotatation: Any) -> type | None:
    origin = get_origin(annotatation) or annotatation
    if isinstance(origin, type):
        return origin


class Reference(Generic[T]):
    """Hide an object behind a reference.

    Used to opt out of the naming/parent-child relationship of `Device`.

    For example::

        class DeviceWithRefToSignal(Device):
            def __init__(self, signal: SignalRW[int]):
                self.signal_ref = Reference(signal)
                super().__init__()

            def set(self, value) -> AsyncStatus:
                return self.signal_ref().set(value + 1)

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

    >>> parent = LazyMock()
    >>> child = parent.child("child")
    >>> child_mock = child()
    >>> child_mock()  # doctest: +ELLIPSIS
    <Mock name='mock.child()' id='...'>
    >>> parent_mock = parent()
    >>> parent_mock.mock_calls
    [call.child()]
    """

    def __init__(self, name: str = "", parent: LazyMock | None = None) -> None:
        self.parent = parent
        self.name = name
        self._mock: Mock | None = None

    def child(self, name: str) -> LazyMock:
        return LazyMock(name, self)

    def __call__(self) -> Mock:
        if self._mock is None:
            self._mock = Mock(spec=object)
            if self.parent is not None:
                self.parent().attach_mock(self._mock, self.name)
        return self._mock
