from __future__ import annotations

import asyncio
import logging
from typing import (
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

import numpy as np
from bluesky.protocols import Reading

T = TypeVar("T")
Callback = Callable[[T], None]

#: A function that will be called with the Reading and value when the
#: monitor updates
ReadingValueCallback = Callable[[Reading, T], None]
DEFAULT_TIMEOUT = 10.0
ErrorText = Union[str, Dict[str, Exception]]


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
                f"Unexpected type `{type(self._errors)}` " "expected `str` or `dict`"
            )

        if isinstance(self._errors, str):
            return " " + self._errors + "\n"

        string = "\n"
        for name, error in self._errors.items():
            string += self._format_sub_errors(name, error, indent=indent)
        return string

    def __str__(self) -> str:
        return self.format_error_string(indent="")


async def wait_for_connection(**coros: Awaitable[None]):
    """Call many underlying signals, accumulating exceptions and returning them

    Expected kwargs should be a mapping of names to coroutine tasks to execute.
    """
    results = await asyncio.gather(*coros.values(), return_exceptions=True)
    exceptions = {}

    for name, result in zip(coros, results):
        if isinstance(result, Exception):
            exceptions[name] = result
            if not isinstance(result, NotConnected):
                logging.exception(
                    f"device `{name}` raised unexpected exception "
                    f"{type(result).__name__}",
                    exc_info=result,
                )

    if exceptions:
        raise NotConnected(exceptions)


def get_dtype(typ: Type) -> Optional[np.dtype]:
    """Get the runtime dtype from a numpy ndarray type annotation

    >>> import numpy.typing as npt
    >>> import numpy as np
    >>> get_dtype(npt.NDArray[np.int8])
    dtype('int8')
    """
    if getattr(typ, "__origin__", None) == np.ndarray:
        # datatype = numpy.ndarray[typing.Any, numpy.dtype[numpy.float64]]
        # so extract numpy.float64 from it
        return np.dtype(typ.__args__[1].__args__[0])  # type: ignore
    elif typ == str:
        return np.dtype("U")  # Unicode string type
    return None


def get_unique(values: Dict[str, T], types: str) -> T:
    """If all values are the same, return that value, otherwise return TypeError

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
    coros: Iterable[Awaitable[Dict[str, T]]],
) -> Dict[str, T]:
    """Merge dictionaries produced by a sequence of coroutines.

    Can be used for merging ``read()`` or ``describe``. For instance::

        combined_read = await merge_gathered_dicts(s.read() for s in signals)
    """
    ret: Dict[str, T] = {}
    for result in await asyncio.gather(*coros):
        ret.update(result)
    return ret


async def gather_list(coros: Iterable[Awaitable[T]]) -> List[T]:
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
