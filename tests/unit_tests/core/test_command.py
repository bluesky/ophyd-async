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
from ophyd_async.core import Array1D, StrictEnum, Table
import pytest
from typing import Any, Dict, Optional, Sequence, Type
from event_model import DataKey

# ---- Define enums and dummy table ----
class CommandEnum(StrictEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"

class DummyTable(Table):
    pass

# ---- CommandCase container ----
CommandCase = namedtuple(
    "CommandCase",
    ["type", "input_val", "output_val", "id", "units", "precision", "expected_datakey"],
)

# ---- Helper ----
def arr(dtype, *vals) -> Array1D:
    """Return a 1D numpy array with a specific dtype."""
    return np.array(vals, dtype=dtype)


def build_datakey(value, units=None, precision=None):
    """Infer the correct DataKey from the value and metadata."""
    # Primitive types
    if isinstance(value, bool):
        dtype, dtype_numpy, shape = "boolean", "?", []
    elif isinstance(value, (int, np.integer)):
        dtype, dtype_numpy, shape = "integer", np.dtype(type(value)).str, []
    elif isinstance(value, (float, np.floating)):
        dtype, dtype_numpy, shape = "number", np.dtype(type(value)).str, []
    elif isinstance(value, str):
        dtype, dtype_numpy, shape = "string", "<U", []
    elif isinstance(value, StrictEnum):
        dtype, dtype_numpy, shape = "string", "<U", []

    # Array types
    elif isinstance(value, np.ndarray):
        dtype, dtype_numpy, shape = "array", value.dtype.str, list(value.shape)

    # Sequence types
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 0:
            # Empty sequence — no dtype info
            dtype_numpy = "<U"
        else:
            first = value[0]
            if isinstance(first, bool):
                dtype_numpy = "?"
            elif isinstance(first, (int, np.integer)):
                dtype_numpy = np.dtype(type(first)).str
            elif isinstance(first, (float, np.floating)):
                dtype_numpy = np.dtype(type(first)).str
            else:
                dtype_numpy = "<U"
        dtype, shape = "array", [len(value)]

    # Table types
    elif isinstance(value, Table):
        dtype, dtype_numpy, shape = "object", "O", []

    # Fallback
    else:
        dtype, dtype_numpy, shape = "object", "O", []

    # Build DataKey
    key = DataKey(
        dtype=dtype,
        dtype_numpy=dtype_numpy,
        shape=shape,
        source="softcmd://expected",
    )
    if units is not None:
        key["units"] = units
    if precision is not None:
        key["precision"] = precision
    if key["dtype"] != "array":
        del key["dtype_numpy"]
    return key


# ---- Build the test matrix ----
test_cases = [
    # === Primitive Types ===
    CommandCase(int, 1, 2, "int", "unit", 0, build_datakey(1, "unit", 0)),
    CommandCase(float, 1.23, 4.56, "float", "unit", 2, build_datakey(1.23, "unit", 2)),
    CommandCase(str, "in", "out", "str", None, None, build_datakey("in")),
    CommandCase(bool, True, False, "bool", None, None, build_datakey(True)),

    # === Enum ===
    CommandCase(CommandEnum, CommandEnum.A, CommandEnum.B, "enum", None, None, build_datakey(CommandEnum.A)),

    # === Array1D (various dtypes) ===
    CommandCase(Array1D[np.bool_], arr(np.bool_, True, False), arr(np.bool_, False, True),
        "array_bool", None, None, build_datakey(arr(np.bool_, True, False))),
    CommandCase(Array1D[np.int8], arr(np.int8, 1, 2, 3), arr(np.int8, 4, 5, 6),
        "array_int8", "unit", 0, build_datakey(arr(np.int8, 1, 2, 3), "unit", 0)),
    CommandCase(Array1D[np.uint8], arr(np.uint8, 1, 2, 3), arr(np.uint8, 4, 5, 6),
        "array_uint8", "unit", 0, build_datakey(arr(np.uint8, 1, 2, 3), "unit", 0)),
    CommandCase(Array1D[np.float64], arr(np.float64, 1.0, 2.0, 3.0), arr(np.float64, 4.0, 5.0, 6.0),
        "array_float64", "unit", 2, build_datakey(arr(np.float64, 1.0, 2.0, 3.0), "unit", 2)),

    # === Sequence types ===
    CommandCase(Sequence[str], ["a", "b"], ["x", "y"], "seq_str", None, None, build_datakey(["a", "b"])),
    CommandCase(Sequence[CommandEnum], [CommandEnum.A, CommandEnum.B], [CommandEnum.C, CommandEnum.D],
        "seq_enum", None, None, build_datakey([CommandEnum.A, CommandEnum.B])),

    # === Table ===
    CommandCase(DummyTable, DummyTable(), DummyTable(), "table", None, None, build_datakey(DummyTable())),
]

def assert_equal(result, expected):
    if isinstance(result, np.ndarray):
        assert np.all(result == expected)
    else:
        assert result == expected

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

@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_sync(case):
    """It should initialize correctly and call a sync callback for all test cases."""

    def callback(a: case.type) -> case.type:
        # Return the expected output regardless of input
        return case.output_val

    backend = SoftCommandBackend(
        command_args=[case.type],
        command_return=case.type,
        command_cb=callback,
        units=case.units,
        precision=case.precision,
    )

    result = await backend.call(case.input_val)
    assert np.all(result == case.output_val) if isinstance(result, np.ndarray) else result == case.output_val
    assert np.all(backend._last_return_value == case.output_val) if isinstance(case.output_val, np.ndarray) else backend._last_return_value == case.output_val


# --- Parametrized async callback test ---
@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_async(case):
    """It should handle async callbacks for all test cases."""

    async def async_callback(a: case.type) -> case.type:
        await asyncio.sleep(0.001)
        return case.output_val

    backend = SoftCommandBackend(
        command_args=[case.type],
        command_return=case.type,
        command_cb=async_callback,
        units=case.units,
        precision=case.precision,
    )

    result = await backend.call(case.input_val)
    assert np.all(result == case.output_val) if isinstance(result, np.ndarray) else result == case.output_val
    assert np.all(backend._last_return_value == case.output_val) if isinstance(case.output_val, np.ndarray) else backend._last_return_value == case.output_val

@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_sync_multiple_inputs(case):
    """It should initialize correctly and call a sync callback with multiple args."""

    def callback(a: case.type, b: int) -> case.type:
        # The second argument is ignored; we just return the expected output
        return case.output_val

    backend = SoftCommandBackend(
        command_args=[case.type, int],
        command_return=case.type,
        command_cb=callback,
        units=case.units,
        precision=case.precision,
    )

    result = await backend.call(case.input_val, 10)
    assert_equal(result, case.output_val)
    assert_equal(backend._last_return_value, case.output_val)


# --- Parametrized async callback test with 2 arguments ---
@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_async_multiple_inputs(case):
    """It should handle async callbacks with multiple args."""

    async def async_callback(a: case.type, b: int) -> case.type:
        await asyncio.sleep(0.001)
        return case.output_val

    backend = SoftCommandBackend(
        command_args=[case.type, int],
        command_return=case.type,
        command_cb=async_callback,
        units=case.units,
        precision=case.precision,
    )

    result = await backend.call(case.input_val, 10)
    assert_equal(result, case.output_val)
    assert_equal(backend._last_return_value, case.output_val)

def test_signature_mismatch_arg_count():
    """It should raise if callback args don't match command_args."""
    def cb(a: int, b: int): return a + b

    with pytest.raises(TypeError, match="Number of command_args"):
        SoftCommandBackend(
            command_args=[int],
            command_return=int,
            command_cb=cb
        )

def test_signature_mismatch_arg_type():
    """It should raise if callback param types don't match command_args."""
    def cb(a: str) -> int: return int(a)

    with pytest.raises(TypeError, match="command_args type"):
        SoftCommandBackend(
            command_args=[int],
            command_return=int,
            command_cb=cb
        )

def test_signature_mismatch_return_type():
    """It should raise if return type doesn't match callback annotation."""
    def cb(a: int) -> str:
        return str(a)

    with pytest.raises(TypeError, match="command_return type"):
        SoftCommandBackend(
            command_args=[int],
            command_return=int,
            command_cb=cb
        )

@pytest.mark.asyncio
async def test_source():
    """It should format the source URI correctly."""
    def cb(a: int) -> int: return a
    backend = SoftCommandBackend([int], int, cb)
    assert backend.source("testcmd", True) == "softcmd://testcmd"

@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c.id for c in test_cases])
async def test_get_datakey_with_metadata_param(case):
    """It should include units, precision, and return the correct DataKey dtype after a call."""

    def cb(x: case.type) -> case.type:
        return case.output_val

    backend = SoftCommandBackend([case.type], case.type, cb, units=case.units, precision=case.precision)
    await backend.call(case.input_val)
    dk = await backend.get_datakey(f"softcmd://{case.id}")

    # Check dtype matches expected
    assert dk["dtype"] == case.expected_datakey["dtype"], f"{case.id}: dtype mismatch"
    # Check shape
    assert dk["shape"] == case.expected_datakey["shape"], f"{case.id}: shape mismatch"
    # Check dtype_numpy for arrays
    if "dtype_numpy" in case.expected_datakey:
        assert dk["dtype_numpy"] == case.expected_datakey["dtype_numpy"], f"{case.id}: dtype_numpy mismatch"
    # Check units and precision
    if case.units is not None:
        assert dk.get("units") == case.units, f"{case.id}: units mismatch"
    if case.precision is not None:
        assert dk.get("precision") == case.precision, f"{case.id}: precision mismatch"

@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c.id for c in test_cases])
async def test_get_datakey_without_last_value_param(case):
    """It should return a valid DataKey even if no call was made."""

    def cb(x: case.type) -> case.type:
        return case.output_val

    backend = SoftCommandBackend([case.type], case.type, cb, units=case.units, precision=case.precision)
    # No call here
    dk = await backend.get_datakey(f"softcmd://{case.id}")

    # The dtype should fall back to the declared command_return_type
    if isinstance(case.output_val, np.ndarray):
        # Array fallback: dtype='array' with dtype_numpy from type
        assert dk["dtype"] == "array", f"{case.id}: dtype mismatch"
    elif isinstance(case.output_val, (bool, int, float, str, StrictEnum)):
        # Primitive fallback
        expected_dtype = case.expected_datakey["dtype"]
        assert dk["dtype"] == expected_dtype, f"{case.id}: dtype mismatch"
    else:
        # Table or object types
        assert dk["dtype"] == "object", f"{case.id}: dtype mismatch"

    # Units and precision should still be included if set
    if case.units is not None:
        assert dk.get("units") == case.units, f"{case.id}: units mismatch"
    if case.precision is not None:
        assert dk.get("precision") == case.precision, f"{case.id}: precision mismatch"

@pytest.mark.asyncio
async def test_call_raises_execution_error():
    """It should wrap exceptions from callback in ExecutionError."""
    def failing_cb(x: int) -> int:
        raise ValueError("boom")

    backend = SoftCommandBackend([int], int, failing_cb)

    with pytest.raises(ExecutionError, match="Command execution failed: boom"):
        await backend.call(5)
    assert backend._last_return_value is None

@pytest.mark.asyncio
async def test_async_lock_context_manager():
    """It should acquire and release the lock properly."""
    def cb(a: int) -> int: return a
    backend = SoftCommandBackend([int], int, cb)

    acquired = []
    async with backend._async_lock():
        assert backend._lock.locked()
        acquired.append(True)
    assert acquired == [True]
    assert not backend._lock.locked()