from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock

from ._command import Command, CommandConnector, MockCommandBackend, MockExecuteCallback
from ._device import Device, DeviceMock
from ._mock_signal_backend import MockPutCallback, MockSignalBackend
from ._signal import Signal, SignalConnector, SignalR
from ._signal_backend import SignalDatatypeT


def get_mock(device: Device | Signal) -> Mock:
    """Return the mock (which may have child mocks attached) for a Device.

    The device must have been connected in mock mode.
    """
    mock = device._mock  # noqa: SLF001
    if not isinstance(mock, DeviceMock):
        msg = f"Device {device} not connected in mock mode"
        raise RuntimeError(msg)
    return mock()


def _get_mock_signal_backend(signal: Signal) -> MockSignalBackend:
    connector = signal._connector  # noqa: SLF001
    if not isinstance(connector, SignalConnector):
        raise TypeError(f"Expected Signal, got {signal}")
    if not isinstance(connector.backend, MockSignalBackend):
        raise RuntimeError(f"Signal {signal} not connected in mock mode")
    return connector.backend


def set_mock_value(signal: Signal[SignalDatatypeT], value: SignalDatatypeT):
    """Set the value of a signal that is in mock mode."""
    backend = _get_mock_signal_backend(signal)
    backend.set_value(value)


class _SetValuesIterator(Iterator[SignalDatatypeT]):
    # Garbage collected by the time __del__ is called unless we put it as a
    # global attrbute here.
    require_all_consumed: bool = False

    def __init__(
        self,
        signal: SignalR[SignalDatatypeT],
        values: Iterable[SignalDatatypeT],
        require_all_consumed: bool = False,
    ):
        self.signal = signal
        self.values = values
        self.require_all_consumed = require_all_consumed
        self.index = 0
        self.iterator = enumerate(values, start=1)

    def __next__(self) -> SignalDatatypeT:
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
    signal: SignalR[SignalDatatypeT],
    values: Iterable[SignalDatatypeT],
    require_all_consumed: bool = False,
) -> Iterator[SignalDatatypeT]:
    """Set a signal to a sequence of values, optionally repeating.

    :param signal: A signal connected in mock mode.
    :param values:
        An iterable of the values to set the signal to, on each iteration the
        next value will be set.
    :param require_all_consumed:
        If True, an AssertionError will be raised if the iterator is deleted
        before all values have been consumed.

    :example:
    ```python
    for value_set in set_mock_values(signal, range(3)):
        # do something

    cm = set_mock_values(signal, [1, 3, 8], require_all_consumed=True):
    next(cm) # do something
    ```
    """
    return _SetValuesIterator(
        signal,
        values,
        require_all_consumed=require_all_consumed,
    )


@contextmanager
def _unset_side_effect_cm(backend: MockSignalBackend):
    yield
    backend.set_mock_put_callback(None)


def callback_on_mock_put(signal: Signal[SignalDatatypeT], callback: MockPutCallback):
    """For setting a callback when a backend is put to.

    Can either be used in a context, with the callback being unset on exit, or
    as an ordinary function.

    The value that the callback returns (if not None) will be set to the signal
    readback. If None is returned then the readback will be set to the setpoint.

    :param signal: A signal with a `MockSignalBackend` backend.
    :param callback: The callback to call when the backend is put to during the
        context.
    """
    backend = _get_mock_signal_backend(signal)
    backend.set_mock_put_callback(callback)
    return _unset_side_effect_cm(backend)


def set_mock_put_proceeds(signal: Signal, proceeds: bool):
    """Allow or block a put with wait=True from proceeding."""
    backend = _get_mock_signal_backend(signal)

    if proceeds:
        backend.put_proceeds.set()
    else:
        backend.put_proceeds.clear()


@contextmanager
def mock_puts_blocked(*signals: Signal):
    """Context manager to block puts at the start and unblock at the end."""
    for signal in signals:
        set_mock_put_proceeds(signal, False)
    yield
    for signal in signals:
        set_mock_put_proceeds(signal, True)


def get_mock_put(signal: Signal) -> AsyncMock:
    """Get the mock associated with the put call on the signal."""
    return _get_mock_signal_backend(signal).put_mock


def _get_mock_command_backend(command: Command) -> MockCommandBackend:
    connector = command._connector  # noqa: SLF001
    if not isinstance(connector, CommandConnector):
        raise TypeError(f"Expected Command, got {command}")
    if not isinstance(connector.backend, MockCommandBackend):
        raise RuntimeError(f"Command {command} not connected in mock mode")
    return connector.backend


def get_mock_execute(command: Command) -> AsyncMock:
    """Get the mock associated with the execute call on a command.

    The command must have been connected in mock mode.
    """
    return _get_mock_command_backend(command).execute_mock


@contextmanager
def _unset_execute_callback_cm(backend: MockCommandBackend):
    yield
    backend.set_mock_execute_callback(None)


def callback_on_mock_execute(command: Command, callback: MockExecuteCallback):
    """Set a callback to be called whenever a Command is executed in mock mode.

    Can either be used as a context manager, with the callback cleared on exit,
    or as a plain function call for a persistent override.

    When the initial backend is a `SoftCommandBackend` the original Python
    function is used by default; set a callback here to suppress it and return
    something else instead.

    :param command: A command connected in mock mode.
    :param callback: The callback to call when the command is executed.
    """
    backend = _get_mock_command_backend(command)
    backend.set_mock_execute_callback(callback)
    return _unset_execute_callback_cm(backend)
