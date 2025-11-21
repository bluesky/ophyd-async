import asyncio
from collections import namedtuple
from collections.abc import Sequence
from typing import (
    Any,
)
from unittest.mock import AsyncMock

import numpy as np
import pytest

# Assuming these are imported from your module
from ophyd_async.core import (
    Array1D,
    ConnectionError,
    ExecutionError,
    LazyMock,
    MockCommandBackend,
    SoftCommandBackend,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    soft_command_r,
    soft_command_rw,
    soft_command_w,
    soft_command_x,
)


# ---- Define enums and dummy table ----
class CommandStrictEnum(StrictEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CommandSubsetEnum(SubsetEnum):
    A = "A"
    B = "B"


class CommandSupersetEnum(SupersetEnum):
    A = "A"


class DummyTable(Table):
    a: Array1D[np.int32]
    b: Sequence[str]

    def __init__(self, a=None, b=None):
        super().__init__(
            a=np.array([] if a is None else a, dtype=np.int32), b=[] if b is None else b
        )


# ---- CommandCase container ----
CommandCase = namedtuple(
    "CommandCase",
    [
        "input_types",
        "output_type",
        "input_val",
        "output_val",
        "id",
        "units",
        "precision",
    ],
)

# ---- Build the test matrix ----
test_cases = [
    # === Primitive Types ===
    CommandCase([int], int, 0, 1, "int", "keV", 0),
    CommandCase([float], float, 0.0, 1.0, "float", "keV", 2),
    CommandCase([str], str, "in", "out", "str", None, None),
    CommandCase([bool], bool, True, False, "bool", None, None),
    # === Enum Types ===
    CommandCase(
        [CommandStrictEnum],
        CommandStrictEnum,
        CommandStrictEnum.A,
        CommandStrictEnum.B,
        "strict_enum",
        None,
        None,
    ),
    CommandCase(
        [CommandSubsetEnum],
        CommandSubsetEnum,
        CommandSubsetEnum.A,
        CommandSubsetEnum.B,
        "subset_enum",
        None,
        None,
    ),
    CommandCase(
        [CommandSupersetEnum],
        CommandSupersetEnum,
        CommandSupersetEnum.A,
        CommandSupersetEnum.A,
        "superset_enum",
        None,
        None,
    ),
    # === Array1D (various dtypes) ===
    CommandCase(
        [Array1D[np.bool_]],
        Array1D[np.bool_],
        np.array([True, False], dtype=bool),
        np.array([False, True], dtype=bool),
        "array_bool",
        None,
        None,
    ),
    CommandCase(
        [Array1D[np.int8]],
        Array1D[np.int8],
        np.array([1, 2, 3], dtype=np.int8),
        np.array([4, 5, 6], dtype=np.int8),
        "array_int8",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.uint8]],
        Array1D[np.uint8],
        np.array([1, 2, 3], dtype=np.uint8),
        np.array([4, 5, 6], dtype=np.uint8),
        "array_uint8",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.int16]],
        Array1D[np.int16],
        np.array([1, 2, 3], dtype=np.int16),
        np.array([4, 5, 6], dtype=np.int16),
        "array_int16",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.uint16]],
        Array1D[np.uint16],
        np.array([1, 2, 3], dtype=np.uint16),
        np.array([4, 5, 6], dtype=np.uint16),
        "array_uint16",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.int32]],
        Array1D[np.int32],
        np.array([1, 2, 3], dtype=np.int32),
        np.array([4, 5, 6], dtype=np.int32),
        "array_int32",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.uint32]],
        Array1D[np.uint32],
        np.array([1, 2, 3], dtype=np.uint32),
        np.array([4, 5, 6], dtype=np.uint32),
        "array_uint32",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.int64]],
        Array1D[np.int64],
        np.array([1, 2, 3], dtype=np.int64),
        np.array([4, 5, 6], dtype=np.int64),
        "array_int64",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.uint64]],
        Array1D[np.uint64],
        np.array([1, 2, 3], dtype=np.uint64),
        np.array([4, 5, 6], dtype=np.uint64),
        "array_uint64",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.float32]],
        Array1D[np.float32],
        np.array([1.0, 2.0, 3.0], dtype=np.float32),
        np.array([4.0, 5.0, 6.0], dtype=np.float32),
        "array_float32",
        "keV",
        0,
    ),
    CommandCase(
        [Array1D[np.float64]],
        Array1D[np.float64],
        np.array([1.0, 2.0, 3.0], dtype=np.float64),
        np.array([4.0, 5.0, 6.0], dtype=np.float64),
        "array_float64",
        "keV",
        0,
    ),
    CommandCase(
        [np.ndarray],
        np.ndarray,
        np.array([1.0, 2.0, 3.0]),
        np.array([4.0, 5.0, 6.0]),
        "array_float64",
        "keV",
        0,
    ),
    # === Sequence types ===
    CommandCase(
        [Sequence[str]], Sequence[str], ["a", "b"], ["x", "y"], "seq_str", None, None
    ),
    CommandCase(
        [Sequence[CommandStrictEnum]],
        Sequence[CommandStrictEnum],
        [CommandStrictEnum.A],
        [CommandStrictEnum.B],
        "seq_enum",
        None,
        None,
    ),
    CommandCase(
        [Sequence[CommandSubsetEnum]],
        Sequence[CommandSubsetEnum],
        [CommandSubsetEnum.A],
        [CommandSubsetEnum.B],
        "seq_enum",
        None,
        None,
    ),
    CommandCase(
        [Sequence[CommandSupersetEnum]],
        Sequence[CommandSupersetEnum],
        [CommandSupersetEnum.A],
        [CommandSupersetEnum.A],
        "seq_enum",
        None,
        None,
    ),
    # === Table ===
    CommandCase(
        [DummyTable], DummyTable, DummyTable(), DummyTable(), "table", None, None
    ),
    # === Multiple Input Types ===
    CommandCase(
        [int, str, Array1D[np.float32]],
        float,
        [0, "a", np.array([1, 2, 3], dtype=np.int8)],
        10.0,
        "multi_input",
        "keV",
        1,
    ),
    # === Read-only ===
    CommandCase(None, float, None, 10.0, "read_only", "keV", 1),
    # === Write-only ===
    CommandCase([int], None, 1, None, "write-only", None, None),
    # === Execute ===
    CommandCase(None, None, None, None, "execute", None, None),
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

    # Set up call method
    backend.call = AsyncMock(return_value=return_value)

    return backend


@pytest.mark.parametrize("test_case", test_cases, ids=[case.id for case in test_cases])
@pytest.mark.asyncio
async def test_mock_command_backend(test_case):
    """Test MockCommandBackend with various input and output types."""

    # Create dummy backend
    dummy = dummy_backend(test_case.output_val)

    # Initialize MockCommandBackend
    backend = MockCommandBackend(dummy, LazyMock())

    # Test source method
    assert backend.source("name", read=True) == ("mock+dummy://name")

    # Test connect method
    with pytest.raises(ConnectionError) as exc_info:
        await backend.connect(0.1)
    assert ("It is not possible to connect a MockCommandBackend") in str(exc_info.value)

    # Test call method
    return_value = await backend.call(test_case.input_val)
    if isinstance(test_case.output_val, np.ndarray):
        assert np.array_equal(return_value, test_case.output_val)
    else:
        assert return_value == test_case.output_val

    # Verify call was recorded
    backend.call_mock.assert_awaited_once_with(test_case.input_val)
    assert backend.call_mock.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_sync(case):
    """It should initialize correctly and call a sync callback for all test cases."""
    if case.id == "multi_input":

        def callback(a: int, b: str, c: Array1D[np.float32]) -> case.output_type:
            return case.output_val
    elif case.id == "read_only":

        def callback() -> float:
            return case.output_val
    elif case.id == "execute":

        def callback() -> None:
            return case.output_val
    else:

        def callback(a: case.input_types[0]) -> case.output_type:
            # Return the expected output regardless of input
            return case.output_val

    backend = SoftCommandBackend(
        command_args=case.input_types,
        command_return=case.output_type,
        command_cb=callback,
        units=case.units,
        precision=case.precision,
    )

    if case.id == "multi_input":
        result = await backend.call(
            case.input_val[0], case.input_val[1], case.input_val[2]
        )
    elif case.id == "read_only":
        result = await backend.call()
    elif case.id == "execute":
        result = await backend.call()
    else:
        result = await backend.call(case.input_val)
    try:
        assert result == case.output_val
    except ValueError:
        assert np.array_equal(result, case.output_val)


# --- Parametrized async callback test ---
@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[tc.id for tc in test_cases])
async def test_valid_initialization_and_call_async(case):
    """It should handle async callbacks for all test cases."""
    if case.id == "multi_input":

        async def async_callback(
            a: int, b: str, c: Array1D[np.float32]
        ) -> case.output_type:
            await asyncio.sleep(0.001)
            return case.output_val
    elif case.id == "read_only":

        async def async_callback() -> case.output_type:
            await asyncio.sleep(0.001)
            return case.output_val
    elif case.id == "execute":

        async def async_callback() -> case.output_type:
            await asyncio.sleep(0.001)
            return case.output_val
    else:

        async def async_callback(a: case.input_types[0]) -> case.output_type:
            await asyncio.sleep(0.001)
            return case.output_val

    backend = SoftCommandBackend(
        command_args=case.input_types,
        command_return=case.output_type,
        command_cb=async_callback,
        units=case.units,
        precision=case.precision,
    )

    if case.id == "multi_input":
        result = await backend.call(
            case.input_val[0], case.input_val[1], case.input_val[2]
        )
    elif case.id == "read_only":
        result = await backend.call()
    elif case.id == "execute":
        result = await backend.call()
    else:
        result = await backend.call(case.input_val)
    try:
        assert result == case.output_val
    except ValueError:
        assert np.array_equal(result, case.output_val)


def test_signature_mismatch_arg_count():
    """It should raise if callback args don't match command_args."""

    def cb(a: int, b: int):
        return a + b

    with pytest.raises(TypeError, match="Number of command_args"):
        SoftCommandBackend(command_args=[int], command_return=int, command_cb=cb)


def test_signature_mismatch_arg_type():
    """It should raise if callback param types don't match command_args."""

    def cb(a: str) -> int:
        return int(a)

    with pytest.raises(TypeError, match="command_args type"):
        SoftCommandBackend(command_args=[int], command_return=int, command_cb=cb)


def test_signature_mismatch_return_type():
    """It should raise if return type doesn't match callback annotation."""

    def cb(a: int) -> str:
        return str(a)

    with pytest.raises(TypeError, match="command_return type"):
        SoftCommandBackend(command_args=[int], command_return=int, command_cb=cb)


@pytest.mark.asyncio
async def test_source():
    """It should format the source URI correctly."""

    def cb(a: int) -> int:
        return a

    backend = SoftCommandBackend([int], int, cb)
    assert backend.source("testcmd", True) == "softcmd://testcmd"


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

    def cb(a: int) -> int:
        return a

    backend = SoftCommandBackend([int], int, cb)

    acquired = []
    async with backend._async_lock():
        assert backend._lock.locked()
        acquired.append(True)
    assert acquired == [True]
    assert not backend._lock.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c.id for c in test_cases])
async def test_soft_command_r(case: CommandCase):
    """Test soft_command_r (read-only) command factory."""
    if case.id in ("write-only", "exec"):
        pytest.skip("write-only commands don't have a read-only counterpart")
    cmd = soft_command_r(
        command_return=case.output_type,
        command_cb=lambda: case.output_val,
        units=case.units,
        precision=case.precision,
        name=case.id,
    )

    result = await cmd.call()
    if isinstance(result, np.ndarray):
        assert np.array_equal(result, case.output_val)
    else:
        assert result == case.output_val


@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c.id for c in test_cases])
async def test_soft_command_w(case: CommandCase):
    """Test soft_command_w (write-only) command factory."""
    if case.id in ("read-only", "exec"):
        pytest.skip("read-only commands don't have a write-only counterpart")
    elif case.id == "multi_input":

        def callback(a: int, b: str, c: Array1D[np.float32]) -> None:
            return None
    elif case.id == "read_only":
        pytest.skip("read-only commands don't have a write-only counterpart")
    elif case.id == "execute":
        pytest.skip("execute commands don't have a write-only counterpart")
    else:

        def callback(a: case.input_types[0]) -> None:
            # Return the expected output regardless of input
            return None

    cmd = soft_command_w(
        command_args=case.input_types,
        command_cb=callback,
        units=case.units,
        precision=case.precision,
        name=case.id,
    )

    if case.id == "multi_input":
        result = await cmd.call(case.input_val[0], case.input_val[1], case.input_val[2])
    else:
        result = await cmd.call(case.input_val)
    try:
        assert result is None
    except ValueError:
        assert np.array_equal(result, case.output_val)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", test_cases, ids=[c.id for c in test_cases])
async def test_soft_command_rw(case: CommandCase):
    """Test soft_command_rw (read-write) command factory."""
    if case.id == "multi_input":

        def callback(a: int, b: str, c: Array1D[np.float32]) -> case.output_type:
            return case.output_val
    elif case.id == "read_only":

        def callback() -> float:
            return case.output_val
    elif case.id == "execute":

        def callback() -> None:
            return case.output_val
    else:

        def callback(a: case.input_types[0]) -> case.output_type:
            # Return the expected output regardless of input
            return case.output_val

    cmd = soft_command_rw(
        command_args=case.input_types,
        command_return=case.output_type,
        command_cb=callback,
        units=case.units,
        precision=case.precision,
        name=case.id,
    )

    if case.id == "multi_input":
        result = await cmd.call(case.input_val[0], case.input_val[1], case.input_val[2])
    elif case.id == "read_only":
        result = await cmd.call()
    elif case.id == "execute":
        result = await cmd.call()
    else:
        result = await cmd.call(case.input_val)
    try:
        assert result == case.output_val
    except ValueError:
        assert np.array_equal(result, case.output_val)


@pytest.mark.asyncio
async def test_soft_command_x():
    """Test soft_command_x (executable, no input/output)
    command factory."""
    called = {"ok": False}

    def cb():
        called["ok"] = True

    cmd = soft_command_x(
        command_cb=cb,
        units="kev",
        precision=1,
        name="execute",
    )

    await cmd.call()
    assert called["ok"]


@pytest.mark.asyncio
async def test_soft_command_rw_with_different_ordering():
    def callback(
        a: int, b: float, scale: int = 1, offset: float = 0.0, label: str = "default"
    ) -> float:
        # Simple linear operation so we can easily validate that kwargs were used
        return a * scale + b + offset

    cmd = soft_command_rw(
        command_args=[int, float, int, float, str],
        command_return=float,
        command_cb=callback,
        name="ordering",
        units="arb",
        precision=2,
    )

    # Call with both positional and keyword arguments
    result = await cmd.call(2, 3.0, label="new", offset=5.0, scale=2)

    # Expected: 2 * 10.0 + 3.0 + 5.0 = 28.0
    assert result == 12.0
