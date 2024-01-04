import asyncio
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Type, TypeVar

import numpy as np
from bluesky.protocols import Reading

T = TypeVar("T")
Callback = Callable[[T], None]

#: A function that will be called with the Reading and value when the
#: monitor updates
ReadingValueCallback = Callable[[Reading, T], None]
DEFAULT_TIMEOUT = 10.0


class ConnectionTimeoutError(TimeoutError):
    """Exception to be raised if a `Device.connect` has timed out."""

    def __init__(self, *lines: str):
        self.lines = list(lines)

    def __str__(self) -> str:
        return "\n".join(self.lines)


class NotConnected(Exception):
    """Exception to be raised if a `Device.connect` is cancelled"""


async def wait_for_connection(**coros: Awaitable[None]):
    """Call many underlying signals, accumulating `ConnectionTimeoutError` exceptions

    Expected kwargs should be a mapping of names to coroutine tasks to execute.

    Raises
    ------
    `ConnectionTimeoutError` if tasks timeout.
    """
    names = coros.keys()
    results = await asyncio.gather(*coros.values(), return_exceptions=True)

    lines: List[str] = []
    for name, result in zip(names, results):
        if isinstance(result, ConnectionTimeoutError):
            lines.append(f"{name}: {result.lines[0]}")
        elif isinstance(result, Exception):
            raise result

    if lines:
        raise ConnectionTimeoutError(*lines)


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
