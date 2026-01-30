import logging
from collections.abc import Sequence
from typing import get_origin

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    Command,
    DeviceMock,
    MockCommandBackend,
    SoftCommandBackend,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    soft_command_rw,
    soft_command_x,
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


# List of types and sample values to test
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

    backend = SoftCommandBackend([datatype], datatype, callback)
    cmd = Command(backend, name="test_cmd")
    await cmd.connect()

    res = await cmd(value)
    if isinstance(value, np.ndarray):
        assert np.array_equal(res, value)
    elif isinstance(value, Table):
        assert res == value
    else:
        assert res == value


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
def test_soft_command_init_validation(datatype, value):
    def callback(v: datatype) -> datatype:
        return v

    # Should succeed
    SoftCommandBackend([datatype], datatype, callback)

    # Should fail if args mismatch
    with pytest.raises(TypeError, match="Number of command_args"):
        SoftCommandBackend([], datatype, callback)

    # Should fail if return type mismatch
    # (Using int as a mismatched type, assuming datatype is not int or is incompatible)
    wrong_type = str if datatype is int else int
    with pytest.raises(TypeError, match="command_return type"):
        SoftCommandBackend([datatype], wrong_type, callback)


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
async def test_soft_command_runtime_validation(datatype, value):
    def callback(v: datatype) -> None:
        pass

    backend = SoftCommandBackend([datatype], None, callback)
    cmd = Command(backend, name="test_cmd")
    await cmd.connect()

    # Wrong number of arguments
    with pytest.raises(TypeError, match="Expected 1 arguments, got 0"):
        await cmd()

    # Wrong type of argument
    wrong_value = (
        ("not the right type",) if datatype is not str else (123,)
    )  # tuple for Sequence
    if get_origin(datatype) is Sequence:
        wrong_value = 123  # Not a sequence
    elif isinstance(value, np.ndarray):
        wrong_value = "not an array"

    with pytest.raises(TypeError, match="should be"):
        await cmd(wrong_value)


async def test_mock_command_backend():
    async def async_callback(a: int, b: str) -> str:
        return f"{b}_{a}"

    backend = SoftCommandBackend([int, str], str, async_callback)
    cmd = Command(backend, name="test_cmd")

    mock = DeviceMock()
    await cmd.connect(mock=mock)

    assert isinstance(cmd._connector.backend, MockCommandBackend)

    cmd._connector.backend.call_mock.return_value = "mock_res"
    res = await cmd(3, "mock")
    assert res == "mock_res"
    cmd._connector.backend.call_mock.assert_called_once_with(3, "mock")


async def test_factory_functions():
    cmd_rw = soft_command_rw([int], str, lambda x: str(x), name="rw")
    await cmd_rw.connect()
    assert await cmd_rw(123) == "123"

    cmd_x = soft_command_x(lambda: None, name="x")
    await cmd_x.connect()
    assert await cmd_x() is None


async def test_execution_error_wrapping():
    def failing_callback():
        raise ValueError("Boom")

    backend = SoftCommandBackend([], None, failing_callback)
    cmd = Command(backend, name="test_cmd")
    await cmd.connect()

    with pytest.raises(ValueError, match="Boom"):
        await cmd()


async def test_async_return_type_validation():
    async def async_ret() -> int:
        return 1

    # Should not raise TypeError because it handles Awaitable[int]
    SoftCommandBackend([], int, async_ret)

    async def async_ret_wrong() -> str:
        return "1"

    with pytest.raises(
        TypeError,
        match=r"command_return type <class 'int'> does not match"
        r" callback return type <class 'str'>",
    ):
        SoftCommandBackend([], int, async_ret_wrong)


async def test_command_logging(caplog):
    caplog.set_level(logging.DEBUG)
    cmd = soft_command_rw([int], str, lambda x: str(x), name="mycmd")
    await cmd.connect()
    assert "Connecting to softcmd://mycmd" in caplog.text

    res = await cmd(42)
    assert res == "42"
    assert "Calling command mycmd with args (42,) and kwargs {}" in caplog.text
    assert "Command mycmd returned 42" in caplog.text
