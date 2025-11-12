import pytest
from unittest.mock import AsyncMock, MagicMock
import asyncio
import numpy as np
from typing import Any, Sequence, Optional, Union, Tuple, Awaitable, Callable, TypeVar
from dataclasses import dataclass
from event_model import DataKey
from collections import namedtuple

# Assuming these are imported from your module
from ophyd_async.core import (
    Command, CommandR, CommandW, CommandX, CommandRW,
    CommandConnector, MockCommandBackend, LazyMock,
    CommandError, ExecutionError, ConnectionError, ConnectionTimeoutError, SoftCommandBackend,
    CommandCallback, CommandArguments, CommandReturn
)
from ophyd_async.core import Array1D
import pytest
from typing import Any, Dict, Optional, Sequence, Type
from event_model import DataKey
from ophyd_async.core import StrictEnum

# Define test enum
class TestEnum(StrictEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"

# Define a named tuple to hold test data
TestCase = namedtuple('TestCase', ['type', 'input_val', 'output_val', 'id', 'units', 'precision'])

# Create test cases
test_cases = [
    TestCase(int, 1, 2, "int", 'unit', 0),
    TestCase(float, 1.0, 2.0, "float", 'unit', 1),
    TestCase(str, "input_string", "output_string", "str", None, None),
    TestCase(bool, True, False, "bool", None, None),
    TestCase(TestEnum, TestEnum.C, TestEnum.D, "enum", None, None),
    TestCase(Sequence[str], ["a", "b", "c"], ["d", "e", "f"], "sequence_str", None, None),
    TestCase(Sequence[TestEnum], [TestEnum.A, TestEnum.B], [TestEnum.C, TestEnum.D], "sequence_enum", None, None),
    TestCase(np.ndarray, np.array([1, 2, 3]), np.array([4, 5, 6]), "ndarray_int", 'unit', 0),
    TestCase(np.ndarray, np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]), "ndarray_float", 'unit', 1),
    TestCase(np.ndarray, np.array([True, False, True]), np.array([False, True, False]), "ndarray_bool", None, None),
]

def dummy_backend(return_value: Any = None):
    """Fixture for creating a minimal dummy backend."""
    backend = AsyncMock()
    backend.return_value = return_value

    # Set up required methods
    backend.source = lambda name, read: f"dummy://{name}"
    backend.connect = AsyncMock(return_value=None)

    # Create a simple get_datakey implementation
    async def get_datakey(source: str) -> DataKey:
        return DataKey(
            source=source,
            dtype="number",
            shape=[],
        )
    backend.get_datakey = get_datakey

    # Set up call method
    backend.call = AsyncMock(return_value=return_value)

    return backend

@pytest.mark.parametrize(
    "test_case",
    test_cases,
    ids=[case.id for case in test_cases]
)
@pytest.mark.asyncio
async def test_mock_command_backend(test_case):
    """Test MockCommandBackend with various input and output types."""

    # Create dummy backend
    dummy = dummy_backend(test_case.output_val)

    # Initialize MockCommandBackend
    backend = MockCommandBackend(dummy, LazyMock())

    # Test source method
    assert backend.source("name", read=True) == "mock+dummy://name"

    # Test connect method
    with pytest.raises(ConnectionError) as exc_info:
        await backend.connect(0.1)
    assert "It is not possible to connect a MockCommandBackend" in str(exc_info.value)

    # Test call method
    return_value = await backend.call(test_case.input_val)
    if isinstance(test_case.output_val, np.ndarray):
        assert np.array_equal(return_value, test_case.output_val)
    else:
        assert return_value == test_case.output_val

    # Verify call was recorded
    backend.call_mock.assert_awaited_once_with(test_case.input_val)
    assert backend.call_mock.call_count == 1

    # Test get_datakey method
    dk = await backend.get_datakey("abc")
    assert dk["source"].endswith("abc")

@pytest.mark.asyncio
async def test_mock_command_backend():
    test_val = 10
    dummy = dummy_backend(test_val)
    # init
    backend = MockCommandBackend(dummy, LazyMock())
    assert backend.source("name", read=True) == "mock+dummy://name"
    # connect
    with pytest.raises(ConnectionError) as exc_info:
        assert await backend.connect(0.1) is None
    assert "It is not possible to connect a MockCommandBackend" in str(exc_info.value)

    # Test with single argument
    return_value = await backend.call(test_val)
    assert return_value == 10
    backend.call_mock.assert_awaited_once_with(test_val)
    assert backend.call_mock.call_count == 1

    # Reset mock for next test
    backend.call_mock.reset_mock()

    # Test with multiple arguments
    test_args = (42, 3.14, "test")
    return_value = await backend.call(*test_args, some_keyword="test")
    assert return_value == test_val
    backend.call_mock.assert_awaited_once_with(*test_args, some_keyword="test")
    assert backend.call_mock.call_count == 1

    # get_datakey
    dk = await backend.get_datakey("abc")
    assert dk["source"].endswith("abc")

T = TypeVar('T')

def create_test_callback(
    return_value: Any = None,
    track_calls: bool = True
) -> Callable[..., Union[T, Awaitable[T]]]:
    """
    Create a test callback that can be sync or async and optionally tracks calls.

    Args:
        return_value: The value to return when called
        track_calls: Whether to track call history

    Returns:
        A callable that can be used as a command callback
    """
    call_count = 0
    call_history: Sequence[Tuple[Tuple, Dict]] = []

    if track_calls:
        async def async_callback(*args, **kwargs) -> Any:
            nonlocal call_count, call_history
            call_count += 1
            call_history.append((args, kwargs))
            return return_value

        def sync_callback(*args, **kwargs) -> Any:
            nonlocal call_count, call_history
            call_count += 1
            call_history.append((args, kwargs))
            return return_value

        # Add methods to access the tracking data
        async_callback.get_call_count = lambda: call_count
        async_callback.get_call_history = lambda: call_history
        async_callback.reset = lambda: [call_count.__setitem__(0, 0), call_history.clear()]

        sync_callback.get_call_count = lambda: call_count
        sync_callback.get_call_history = lambda: call_history
        sync_callback.reset = lambda: [call_count.__setitem__(0, 0), call_history.clear()]

        # Return both versions and let the caller choose
        return async_callback, sync_callback

    else:
        async def async_callback(*args, **kwargs) -> Any:
            return return_value

        def sync_callback(*args, **kwargs) -> Any:
            return return_value

        return async_callback, sync_callback

@pytest.mark.parametrize(
    "test_case",
    test_cases,
    ids=[case.id for case in test_cases]
)
@pytest.mark.asyncio
async def test_soft_command_backend(test_case):
    """Test SoftCommandBackend with various input and output types."""
    callback: CommandCallback[CommandArguments, CommandReturn]

    cb = create_test_callback(return_value=test_case.output_val)

    soft_backend = SoftCommandBackend(
        command_args = [test_case.type],
        command_return = [test_case.type],
        command_cb = cb,
        units=test_case.units,
        precision=test_case.precision
    )
    assert soft_backend._command_args == [test_case.type]