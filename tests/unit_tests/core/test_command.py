import asyncio
import logging
from collections.abc import Sequence

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    Command,
    DeviceFiller,
    DeviceMock,
    DeviceVector,
    NotConnectedError,
    SoftCommandBackend,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    make_converter,
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

    backend = SoftCommandBackend(callback)
    cmd = Command(backend, name="test_cmd")
    assert cmd._connector.backend.get_return_type() == datatype
    await cmd.connect()
    status = cmd.execute(value)
    await status
    res = status.value
    if isinstance(value, np.ndarray):
        assert np.array_equal(res, value)
    else:
        assert res == value


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
def test_soft_command_init_validation(datatype, value):
    def missing_param_annotation(v):
        return v

    with pytest.raises(TypeError, match="missing type annotations for parameter"):
        SoftCommandBackend(missing_param_annotation)

    def missing_return_annotation(v: int):
        return v

    with pytest.raises(TypeError, match="missing a return type annotation"):
        SoftCommandBackend(missing_return_annotation)

    def incomplete_param_annotation(v: int, x) -> int:
        return v

    with pytest.raises(TypeError, match="missing type annotations for parameter"):
        SoftCommandBackend(incomplete_param_annotation)


async def test_execute_raises_typeerror_on_bad_arguments():
    async def callback(a: int, b: int) -> int:
        return a + b

    backend = SoftCommandBackend(callback)
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

    backend = SoftCommandBackend(callback)
    cmd = Command(backend, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Execute without setting a callback - should return manufactured default
    status = cmd.execute(value)
    await status

    # Manufactured defaults are: 0 for int/float, "" for str, False for bool, etc.
    # The SoftConverter.write_value(None) is what's called.
    expected_default = make_converter(datatype).write_value(None)

    if isinstance(expected_default, np.ndarray):
        assert np.array_equal(status.value, expected_default)
    elif isinstance(expected_default, Table):
        for field in expected_default.__dict__:
            v1 = getattr(status.value, field)
            v2 = getattr(expected_default, field)
            if isinstance(v1, np.ndarray):
                assert np.array_equal(v1, v2)
            else:
                assert v1 == v2
    else:
        assert status.value == expected_default


async def test_mock_command_backend_custom_callback():
    """Test MockCommandBackend uses the provided custom callback."""

    async def async_callback(a: int, b: str) -> str:
        return f"{b}_{a}"

    backend = SoftCommandBackend(async_callback)
    cmd = Command(backend, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Set custom callback
    cmd._connector.backend.set_mock_execute_callback(lambda a, b: f"mock_{b}_{a}")
    status = cmd.execute(3, "test")
    result = await status
    assert result == "mock_test_3"
    cmd._connector.backend.execute_mock.assert_awaited_once_with(3, "test")


async def test_mock_command_backend_lazy_init():
    """Verify execute_mock is lazy-initialized."""

    async def callback(a: int) -> int:
        return a

    backend = SoftCommandBackend(callback)
    cmd = Command(backend, name="test_cmd")
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

    backend = SoftCommandBackend(callback)
    cmd = Command(backend, name="test_cmd")
    mock = DeviceMock()
    await cmd.connect(mock=mock)

    # Verify source string
    assert cmd._connector.backend.source("test") == "mock+softcmd://test"

    # Verify return type
    assert cmd._connector.backend.get_return_type() is str

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
    assert status.value == "123"

    def x_cb() -> None:
        return None

    cmd_x = soft_command(x_cb, name="x")
    await cmd_x.connect()
    status = cmd_x.execute()
    await status
    assert status.value is None


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
    assert status.value == "42"
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
    backend = SoftCommandBackend(callback)
    cmd = Command(backend, timeout=5.0, name="test_cmd")
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

        return SoftCommandBackend(callback)

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
        assert backend.get_return_type() is int
