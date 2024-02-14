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
ErrorText = Union[str, Dict[str, "ErrorText"]]


class NotConnected(Exception):
    """Exception to be raised if a `Device.connect` is cancelled"""

    _indent_width = "    "

    def __init__(self, errors: ErrorText):
        """
        Not connected holds a mapping of device/signal names to
        subdevices, or further errors in subdevices

        Parameters
        ----------
        errors: ErrorText
            Mapping of device name to error or subdevice with errors.
            Alternatively a string with the signal error.
        """

        self._errors = errors

    def format_error_string(self, errors: ErrorText, indent="") -> str:
        string = ""
        if isinstance(errors, str):
            return f"{errors}\n"
        elif not isinstance(errors, dict):
            raise RuntimeError(
                f"Unknown error type `{type(errors)}` " "expected `str` or `dict`"
            )

        for name, value in errors.items():
            string += indent + f"{name}:"
            if isinstance(value, str):
                string += " " + f"{value}\n"  # On the same line as the name
            elif isinstance(value, dict):
                string += "\n" + self.format_error_string(
                    value, indent=(indent + self._indent_width)
                )
            else:
                raise RuntimeError(f"`{type(value)}` not a string or a dict")
        return string

    def __str__(self) -> str:
        return self.format_error_string(self._errors, indent="")


async def wait_for_connection(**coros: Awaitable[None]):
    """Call many underlying signals, accumulating exceptions and returning them

    Expected kwargs should be a mapping of names to coroutine tasks to execute.
    """
    results = await asyncio.gather(*coros.values(), return_exceptions=True)
    exceptions = {}

    for name, result in zip(coros, results):
        if isinstance(result, Exception):
            if isinstance(result, NotConnected):
                exceptions[name] = result._errors
            else:
                exceptions[name] = f"unexpected exception {type(result).__name__}"
                logging.exception(
                    f"device `{name}` raised unexpected "
                    f"exception {type(result).__name__}",
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
    coros: Iterable[Awaitable[Dict[str, T]]]
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
