import asyncio
import inspect
import logging
from collections.abc import Sequence
from typing import get_origin

import numpy as np
import pytest

from ophyd_async.core import (
    NO_ARG_VOID_SIGNATURE,
    Array1D,
    Command,
    CommandBackend,
    DeviceFiller,
    DeviceMock,
    DeviceVector,
    NotConnectedError,
    SoftCommandBackend,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    TriggerableCommand,
    callback_on_mock_execute,
    get_mock_execute,
    soft_command,
)


class MyStrictEnum(StrictEnum):
    A = "A"
    B = "B"


class MySubsetEnum(SubsetEnum):
    X = "X"
    Y = "Y"


class MySupersetEnum(SupersetEnum):
    P = "P"
    Q = "Q"


class MyTable(Table):
    a: Array1D[np.int32]
    b: Sequence[str]


TEST_PARAMS = [
    (bool, True),
    (int, 42),
    (float, 3.14),
    (str, "hello"),
    (MyStrictEnum, MyStrictEnum.A),
    (MySubsetEnum, MySubsetEnum.X),
    (MySupersetEnum, MySupersetEnum.P),
    (Array1D[np.bool_], np.array([True, False], dtype=np.bool_)),
    (Array1D[np.int8], np.array([1, 2], dtype=np.int8)),
    (Array1D[np.uint8], np.array([1, 2], dtype=np.uint8)),
    (Array1D[np.int16], np.array([1, 2], dtype=np.int16)),
    (Array1D[np.uint16], np.array([1, 2], dtype=np.uint16)),
    (Array1D[np.int32], np.array([1, 2], dtype=np.int32)),
    (Array1D[np.uint32], np.array([1, 2], dtype=np.uint32)),
    (Array1D[np.int64], np.array([1, 2], dtype=np.int64)),
    (Array1D[np.uint64], np.array([1, 2], dtype=np.uint64)),
    (Array1D[np.float32], np.array([1.1, 2.2], dtype=np.float32)),
    (Array1D[np.float64], np.array([1.1, 2.2], dtype=np.float64)),
    (np.ndarray, np.array([[1, 2], [3, 4]])),
    (Sequence[str], ["a", "b"]),
    (Sequence[MyStrictEnum], [MyStrictEnum.A, MyStrictEnum.B]),
    (Sequence[MySubsetEnum], [MySubsetEnum.X, MySubsetEnum.Y]),
    (Sequence[MySupersetEnum], [MySupersetEnum.P, MySupersetEnum.Q]),
    (MyTable, MyTable(a=np.array([1], dtype=np.int32), b=["hi"])),
]


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
async def test_soft_command_execution(datatype, value):
    def callback(v: datatype) -> datatype:
        return v

    cmd = soft_command(callback, name="test_cmd")
    assert cmd.signature == inspect.signature(callback, eval_str=True)
    await cmd.connect()
    status = cmd.execute(value)
    await status
    res = status.result()
    if isinstance(value, np.ndarray):
        assert np.array_equal(res, value)
    else:
        assert res == value


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
def test_soft_command_init_validation(datatype, value):
    def missing_param_annotation(v):
        return v

    with pytest.raises(TypeError, match="missing type annotations for parameter"):
        soft_command(missing_param_annotation)

    def missing_return_annotation(v: int):
        return v

    with pytest.raises(TypeError, match="missing a return type annotation"):
        soft_command(missing_return_annotation)

    def incomplete_param_annotation(v: int, x) -> int:
        return v

    with pytest.raises(TypeError, match="missing type annotations for parameter"):
        soft_command(incomplete_param_annotation)


def test_soft_command_backend_raises_on_unannotated_sig_param():
    """SoftCommandBackend must raise TypeError when the supplied sig has unannotated
    parameters, not silently discard them.  Previously the constructor would just
    omit the converter for those params, meaning no coercion would happen.
    """
    unannotated_sig = inspect.Signature(
        [inspect.Parameter("v", inspect.Parameter.POSITIONAL_OR_KEYWORD)],
        return_annotation=None,
    )

    async def cb(v):
        return None

    with pytest.raises(TypeError, match="missing type annotations for parameter"):
        SoftCommandBackend(cb, unannotated_sig)


async def test_execute_raises_typeerror_on_bad_arguments():
    async def callback(a: int, b: int) -> int:
        return a + b

    sig = inspect.signature(callback, eval_str=True)
    backend = SoftCommandBackend(callback, sig)
    # Too few arguments
    with pytest.raises(TypeError, match="missing a required argument"):
        await backend.execute(1)
    # Too many positional arguments
    with pytest.raises(TypeError, match="too many positional arguments"):
        await backend.execute(1, 2, 3)
    # Unexpected keyword argument
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        await backend.execute(a=1, b=2, c=3)
    # Multiple values for the same argument
    with pytest.raises(TypeError, match="multiple values for argument"):
        await backend.execute(1, a=2)


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
async def test_mock_command_backend_default_values(datatype, value):
    """Test MockCommandBackend returns manufactured defaults for various types."""

    async def callback(v: datatype) -> datatype:
        return v

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Execute without setting a callback - should return manufactured default
    return_value = await cmd.execute(value)
    if get_origin(datatype) is np.ndarray:
        assert get_origin(datatype) is type(return_value)
    elif get_origin(datatype) is Sequence:
        assert type(return_value) is list
    else:
        assert type(return_value) is datatype


async def test_mock_command_backend_custom_callback():
    """Test MockCommandBackend uses the provided custom callback."""

    async def async_callback(a: int, b: str) -> str:
        return f"{b}_{a}"

    cmd = soft_command(async_callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Use callback_on_mock_execute as a context manager
    with callback_on_mock_execute(cmd, lambda a, b: f"mock_{b}_{a}"):
        result = await cmd.execute(3, "test")
    assert result == "mock_test_3"
    get_mock_execute(cmd).assert_awaited_once_with(3, "test")

    # After the context, the original function is restored
    result2 = await cmd.execute(1, "x")
    assert result2 == "x_1"


async def test_soft_command_mock_calls_original_func():
    """soft_command connected in mock mode should still call the original function."""
    calls: list[int] = []

    def callback(v: int) -> int:
        calls.append(v)
        return v * 2

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    result = await cmd.execute(5)
    assert result == 10
    assert calls == [5]


async def test_soft_command_mock_side_effect_overrides_func():
    calls: list[int] = []

    def callback(v: int) -> int:
        calls.append(v)
        return v * 2

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    with callback_on_mock_execute(cmd, lambda v: 99):
        result = await cmd.execute(5)
    assert result == 99
    assert calls == []

    # Outside the context, the original function is called again
    result2 = await cmd.execute(5)
    assert result2 == 10
    assert calls == [5]


async def test_mock_command_backend_lazy_init():
    """Verify execute_mock is lazy-initialized."""

    async def callback(a: int) -> int:
        return a

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # execute_mock should not be in __dict__ before use
    assert "execute_mock" not in cmd._connector.backend.__dict__

    # First execution triggers initialization
    status = cmd.execute(42)
    await status

    assert "execute_mock" in cmd._connector.backend.__dict__


async def test_mock_command_backend_properties():
    """Verify source, return type, and connection behavior."""

    async def callback(a: int) -> str:
        return str(a)

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Verify source string
    assert cmd._connector.backend.source("test") == "mock+softcmd://test"

    # Verify return type
    assert cmd.signature.return_annotation is str

    # Verify connect raises error
    with pytest.raises(NotConnectedError):
        await cmd._connector.backend.connect(1.0)


async def test_soft_command_factory():
    def rw_cb(x: int) -> str:
        return str(x)

    cmd_rw = soft_command(rw_cb, name="rw")
    await cmd_rw.connect()
    status = cmd_rw.execute(123)
    await status
    assert status.result() == "123"

    def x_cb() -> None:
        return None

    cmd_x = soft_command(x_cb, name="x")
    await cmd_x.connect()
    status = cmd_x.execute()
    await status
    assert status.result() is None


async def test_execution_error_wrapping():
    def failing_callback() -> None:
        raise ValueError("Boom")

    cmd = soft_command(failing_callback, name="test_cmd")
    await cmd.connect()
    with pytest.raises(ValueError, match="Boom"):
        await cmd.execute()


async def test_async_return_type_validation():
    async def async_ret() -> int:
        return 1

    soft_command(async_ret)


async def test_command_logging(caplog):
    caplog.set_level(logging.DEBUG)

    def my_cb(x: int) -> str:
        return str(x)

    cmd = soft_command(my_cb, name="mycmd")
    await cmd.connect()
    assert "Connecting to softcmd://mycmd" in caplog.text
    status = cmd.execute(42)
    await status
    assert status.result() == "42"
    assert "Executing command mycmd" in caplog.text
    assert "Command mycmd returned 42" in caplog.text


async def test_command_trigger():
    """Test Command.trigger with and without timeout."""
    callback_called = False

    async def callback() -> None:
        nonlocal callback_called
        callback_called = True
        await asyncio.sleep(0.1)
        return None

    # Setup command
    sig = inspect.signature(callback, eval_str=True)
    backend = SoftCommandBackend(callback, sig)
    cmd = TriggerableCommand(backend, timeout=5.0, name="test_cmd")
    await cmd.connect()

    # Test with default timeout (uses command's timeout)
    status = cmd.trigger()
    await status
    assert callback_called

    # Test with explicit timeout
    status = cmd.trigger(timeout=10.0)
    await status
    assert callback_called

    # Force a timeout
    with pytest.raises(asyncio.TimeoutError):
        await cmd.trigger(timeout=0.05)


async def test_fill_child_command_vector_index():
    """Test fill_child_command when vector_index is provided."""

    def backend_factory(datatype):
        async def callback() -> int:
            return 0

        sig = inspect.signature(callback, eval_str=True)
        return SoftCommandBackend(callback, sig)

    vector: DeviceVector[Command[[], int]] = DeviceVector()
    vector.__orig_class__ = DeviceVector[Command[[], int]]  # type: ignore

    filler = DeviceFiller(
        device=vector,
        signal_backend_factory=lambda _: None,
        device_connector_factory=lambda: None,
        command_backend_factory=backend_factory,
    )

    for i in range(1, 4):
        filler.fill_child_command(
            name="my_cmd",
            command_type=Command,
            vector_index=i,
        )

    assert len(vector) == 3
    for i in range(1, 4):
        assert i in vector
        cmd = vector[i]
        assert isinstance(cmd, Command)
        backend = cmd._connector._init_backend
        assert isinstance(backend, SoftCommandBackend)
        assert backend.signature.return_annotation is int


class _NullSigBackend(CommandBackend):
    """Minimal hardware-like backend that passes signature=None at construction."""

    def source(self, name: str) -> str:
        return f"hw://{name}"

    async def connect(self, timeout: float) -> None:
        pass

    async def execute(self) -> None:
        pass


async def test_mock_command_null_sig_backend_uses_no_arg_void_signature():
    backend = _NullSigBackend(signature=None)
    cmd = TriggerableCommand(backend, name="hw_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    assert cmd.signature == NO_ARG_VOID_SIGNATURE
    assert cmd.signature.return_annotation is None
    assert list(cmd.signature.parameters) == []


async def test_mock_triggerable_command_null_sig_backend():
    backend = _NullSigBackend(signature=None)
    cmd = TriggerableCommand(backend, name="hw_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # trigger() should call through to execute_mock and return None
    await cmd.trigger()

    execute_mock = get_mock_execute(cmd)
    execute_mock.assert_awaited_once()


@pytest.mark.parametrize(
    "datatype, raw, expected",
    [
        (int, "42", 42),
        (float, "3.14", 3.14),
        (bool, 1, True),
        (MyStrictEnum, "A", MyStrictEnum.A),
    ],
)
async def test_mock_command_applies_conversion_like_soft(datatype, raw, expected):
    """MockCommandBackend must apply the same type conversion as SoftCommandBackend.

    When a hardware backend is mocked, calling cmd.execute(raw) with a value that
    needs coercion (e.g. str "42" for int) should arrive at execute_mock already
    converted, exactly as SoftCommandBackend.execute() would convert it.
    """

    def callback(v: datatype) -> datatype:
        return v

    cmd = soft_command(callback, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    await cmd.execute(raw)

    execute_mock = get_mock_execute(cmd)
    # The value recorded by execute_mock must have been converted
    (recorded,), _ = execute_mock.call_args
    assert recorded == expected
    assert type(recorded) is type(expected)
