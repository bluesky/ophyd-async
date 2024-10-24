from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock

from ._mock_signal_backend import MockSignalBackend
from ._signal import Signal
from ._utils import T


def _get_mock_signal_backend(signal: Signal) -> MockSignalBackend:
    backend = signal._backend  # noqa:SLF001
    assert isinstance(backend, MockSignalBackend), (
        "Expected to receive a `MockSignalBackend`, instead "
        f" received {type(backend)}. "
    )
    return backend


def set_mock_value(signal: Signal[T], value: T):
    """Set the value of a signal that is in mock mode."""
    backend = _get_mock_signal_backend(signal)
    backend.set_value(value)


def set_mock_put_proceeds(signal: Signal, proceeds: bool):
    """Allow or block a put with wait=True from proceeding"""
    backend = _get_mock_signal_backend(signal)

    if proceeds:
        backend.put_proceeds.set()
    else:
        backend.put_proceeds.clear()


@asynccontextmanager
async def mock_puts_blocked(*signals: Signal):
    for signal in signals:
        set_mock_put_proceeds(signal, False)
    yield
    for signal in signals:
        set_mock_put_proceeds(signal, True)


def get_mock_put(signal: Signal) -> AsyncMock:
    """Get the mock associated with the put call on the signal."""
    return _get_mock_signal_backend(signal).put_mock


def reset_mock_put_calls(signal: Signal):
    backend = _get_mock_signal_backend(signal)
    backend.put_mock.reset_mock()


class _SetValuesIterator:
    # Garbage collected by the time __del__ is called unless we put it as a
    # global attrbute here.
    require_all_consumed: bool = False

    def __init__(
        self,
        signal: Signal,
        values: Iterable[Any],
        require_all_consumed: bool = False,
    ):
        self.signal = signal
        self.values = values
        self.require_all_consumed = require_all_consumed
        self.index = 0

        self.iterator = enumerate(values, start=1)

    def __iter__(self):
        return self

    def __next__(self):
        # Will propogate StopIteration
        self.index, next_value = next(self.iterator)
        set_mock_value(self.signal, next_value)
        return next_value

    def __del__(self):
        if self.require_all_consumed:
            # Values is cast to a list here because the user has supplied
            # require_all_consumed=True, we can therefore assume they
            # supplied a finite list.
            # In the case of require_all_consumed=False, an infinite
            # iterble is permitted
            values = list(self.values)
            if self.index != len(values):
                # Report the values consumed and the values yet to be
                # consumed
                consumed = values[0 : self.index]
                to_be_consumed = values[self.index :]
                raise AssertionError(
                    f"{self.signal.name}: {consumed} were consumed "
                    f"but {to_be_consumed} were not consumed"
                )


def set_mock_values(
    signal: Signal,
    values: Iterable[Any],
    require_all_consumed: bool = False,
) -> _SetValuesIterator:
    """Iterator to set a signal to a sequence of values, optionally repeating the
    sequence.

    Parameters
    ----------
    signal:
        A signal with a `MockSignalBackend` backend.
    values:
        An iterable of the values to set the signal to, on each iteration
        the value will be set.
    require_all_consumed:
        If True, an AssertionError will be raised if the iterator is deleted before
        all values have been consumed.

    Notes
    -----
    Example usage::

           for value_set in set_mock_values(signal, [1, 2, 3]):
                # do something

            cm = set_mock_values(signal, 1, 2, 3, require_all_consumed=True):
            next(cm)
            # do something
    """

    return _SetValuesIterator(
        signal,
        values,
        require_all_consumed=require_all_consumed,
    )


@contextmanager
def _unset_side_effect_cm(put_mock: AsyncMock):
    yield
    put_mock.side_effect = None


def callback_on_mock_put(
    signal: Signal[T], callback: Callable[[T], None] | Callable[[T], Awaitable[None]]
):
    """For setting a callback when a backend is put to.

    Can either be used in a context, with the callback being
    unset on exit, or as an ordinary function.

    Parameters
    ----------
    signal:
        A signal with a `MockSignalBackend` backend.
    callback:
        The callback to call when the backend is put to during the context.
    """
    backend = _get_mock_signal_backend(signal)
    backend.put_mock.side_effect = callback
    return _unset_side_effect_cm(backend.put_mock)
