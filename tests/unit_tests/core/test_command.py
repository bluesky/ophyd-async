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
    await cmd.connect()

    res = await cmd(value)
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


@pytest.mark.parametrize("datatype, value", TEST_PARAMS)
async def test_soft_command_runtime_validation(datatype, value):
    def callback(v: datatype) -> None:
        pass

    backend = SoftCommandBackend(callback)
    cmd = Command(backend, name="test_cmd")
    await cmd.connect()

    # Wrong number of arguments
    with pytest.raises(TypeError, match="missing a required argument"):
        await cmd()

    # Wrong type of argument
    wrong_value = "not the right type" if datatype is not str else 123
    if get_origin(datatype) is Sequence:
        wrong_value = 123
    elif isinstance(value, np.ndarray):
        wrong_value = "not an array"

    with pytest.raises(TypeError, match="should be"):
        await cmd(wrong_value)


async def test_mock_command_backend():
    async def async_callback(a: int, b: str) -> str:
        return f"{b}_{a}"

    backend = SoftCommandBackend(async_callback)
    cmd = Command(backend, name="test_cmd")

    mock = DeviceMock()
    await cmd.connect(mock=mock)

    assert isinstance(cmd._connector.backend, MockCommandBackend)

    cmd._connector.backend.call_mock.return_value = "mock_res"
    res = await cmd(3, "mock")
    assert res == "mock_res"
    cmd._connector.backend.call_mock.assert_called_once_with(3, "mock")


async def test_soft_command_factory():
    def rw_cb(x: int) -> str:
        return str(x)

    cmd_rw = soft_command(rw_cb, name="rw")
    await cmd_rw.connect()
    assert await cmd_rw(123) == "123"

    def x_cb() -> None:
        return None

    cmd_x = soft_command(x_cb, name="x")
    await cmd_x.connect()
    assert await cmd_x() is None


async def test_execution_error_wrapping():
    def failing_callback() -> None:
        raise ValueError("Boom")

    cmd = soft_command(failing_callback, name="test_cmd")
    await cmd.connect()

    with pytest.raises(ValueError, match="Boom"):
        await cmd()


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

    res = await cmd(42)
    assert res == "42"
    assert "Calling command mycmd with args (42,) and kwargs {}" in caplog.text
    assert "Command mycmd returned 42" in caplog.text
