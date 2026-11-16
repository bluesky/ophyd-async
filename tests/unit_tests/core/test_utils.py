import asyncio
import gc
import re
import sys
from asyncio import CancelledError
from collections.abc import Sequence
from contextlib import nullcontext

import numpy as np
import numpy.typing as npt
from typing import TypeVar, assert_type

import numpy as np
import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Array1D,
    Device,
    gather_dict,
    get_dtype,
    get_unaliased_origin,
    init_devices,
    SoftSignalBackend,
    NotConnectedError,
    SignalRW,
    StrictEnum,
    AsyncStatus,
    callback_on_mock_put,
    cancel_and_wait,
    get_mock_put,
    merge_gathered_dicts,
    set_mock_value,
    simulate_move,
    soft_signal_rw,
)
from ophyd_async.core._utils import _wait_for
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.epics.motor import Motor


class MyEnum(StrictEnum):
    A = "A"


T = TypeVar("T")


class ValueErrorBackend(SoftSignalBackend):
    def __init__(self, exc_text=""):
        self.exc_text = exc_text
        super().__init__(datatype=int)

    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        raise ValueError(self.exc_text)


class WorkingDummyChildDevice(Device):
    def __init__(self, name: str = "working_dummy_child_device") -> None:
        self.working_signal = soft_signal_rw(int)
        super().__init__(name=name)


class TimeoutDummyChildDeviceCA(Device):
    def __init__(self, name: str = "timeout_dummy_child_device_ca") -> None:
        self.timeout_signal = epics_signal_rw(int, "ca://A_NON_EXISTENT_SIGNAL")
        super().__init__(name=name)


class TimeoutDummyChildDevicePVA(Device):
    def __init__(self, name: str = "timeout_dummy_child_device_pva") -> None:
        self.timeout_signal = epics_signal_rw(int, "pva://A_NON_EXISTENT_SIGNAL")
        super().__init__(name=name)


class ValueErrorDummyChildDevice(Device):
    def __init__(
        self, name: str = "value_error_dummy_child_device", exc_text=""
    ) -> None:
        self.value_error_signal = SignalRW(ValueErrorBackend(exc_text=exc_text))
        super().__init__(name=name)


class DummyDeviceOneWorkingOneTimeout(Device):
    def __init__(self, name: str = "dummy_device_one_working_one_timeout") -> None:
        self.working_child_device = WorkingDummyChildDevice()
        self.timeout_child_device = TimeoutDummyChildDeviceCA()
        super().__init__(name=name)


ONE_WORKING_ONE_TIMEOUT_OUTPUT = NotConnectedError(
    {
        "timeout_child_device": NotConnectedError(
            {"timeout_signal": NotConnectedError("ca://A_NON_EXISTENT_SIGNAL")}
        )
    }
)


class DummyDeviceTwoWorkingTwoTimeOutTwoValueError(Device):
    def __init__(
        self,
        name: str = "dummy_device_two_working_one_timeout_two_value_error",
    ) -> None:
        self.working_child_device1 = WorkingDummyChildDevice()
        self.working_child_device2 = WorkingDummyChildDevice()
        self.timeout_child_device_ca = TimeoutDummyChildDeviceCA()
        self.timeout_child_device_pva = TimeoutDummyChildDevicePVA()
        self.value_error_child_device1 = ValueErrorDummyChildDevice(
            exc_text="Some ValueError text"
        )
        self.value_error_child_device2 = ValueErrorDummyChildDevice()
        super().__init__(name=name)


TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT = NotConnectedError(
    {
        "timeout_child_device_ca": NotConnectedError(
            {
                "timeout_signal": NotConnectedError("ca://A_NON_EXISTENT_SIGNAL"),
            }
        ),
        "timeout_child_device_pva": NotConnectedError(
            {"timeout_signal": NotConnectedError("pva://A_NON_EXISTENT_SIGNAL")}
        ),
        "value_error_child_device1": NotConnectedError(
            {"value_error_signal": ValueError("Some ValueError text")}
        ),
        "value_error_child_device2": NotConnectedError(
            {
                "value_error_signal": ValueError(),
            }
        ),
    }
)


class DummyDeviceCombiningTopLevelSignalAndSubDevice(Device):
    def __init__(
        self, name: str = "dummy_device_combining_top_level_signal_and_sub_device"
    ) -> None:
        self.timeout_signal = epics_signal_rw(int, "ca://A_NON_EXISTENT_SIGNAL")
        self.sub_device = ValueErrorDummyChildDevice(exc_text="Some ValueError text")
        super().__init__(name=name)


async def test_error_handling_connection_timeout(caplog):
    caplog.set_level(10)

    dummy_device_one_working_one_timeout = DummyDeviceOneWorkingOneTimeout()

    # This should work since the error is a connection timeout
    with pytest.raises(NotConnectedError) as exc:
        await dummy_device_one_working_one_timeout.connect(timeout=0.01)

    assert str(exc.value) == str(ONE_WORKING_ONE_TIMEOUT_OUTPUT)

    logs = caplog.get_records("call")

    # See https://github.com/bluesky/ophyd-async/issues/519
    # assert len(logs) == 3

    assert "signal ca://A_NON_EXISTENT_SIGNAL timed out" == logs[-1].message
    assert logs[-1].levelname == "DEBUG"


async def test_error_handling_value_errors(caplog):
    """Checks that NotConnectedError is aggregated correctly across Devices."""

    caplog.set_level(10)

    dummy_device_two_working_one_timeout_two_value_error = (
        DummyDeviceTwoWorkingTwoTimeOutTwoValueError("dsf")
    )

    # This should fail since the error is a ValueError
    with pytest.raises(NotConnectedError) as exc:
        await dummy_device_two_working_one_timeout_two_value_error.connect(timeout=0.01)

    assert str(exc.value) == str(TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT)

    logs = caplog.get_records("call")
    logs = [
        log
        for log in logs
        if "ophyd_async" in log.pathname and "_signal" not in log.pathname
    ]
    assert len(logs) == 4

    for i in range(0, 2):
        assert (
            "device `value_error_signal` raised unexpected exception ValueError"
            == logs[i].message
        )
        assert logs[i].levelname == "ERROR"

    assert logs[2].levelname == "DEBUG"
    assert logs[3].levelname == "DEBUG"
    # These messages could come in any order
    messages = [logs[idx].message for idx in (2, 3)]
    for protocol in ("pva", "ca"):
        assert f"signal {protocol}://A_NON_EXISTENT_SIGNAL timed out" in messages


class BadDatatypeDevice(Device):
    def __init__(self, name: str = "") -> None:
        self.sig = epics_signal_rw(object, "", "")
        super().__init__(name)


async def test_error_handling_init_devices_mock():
    with pytest.raises(NotConnectedError) as exc:
        async with init_devices(mock=True):
            device = BadDatatypeDevice()
            device2 = BadDatatypeDevice()
    expected_output = NotConnectedError(
        {
            "device": NotConnectedError(
                {"sig": TypeError(f"Can't make converter for {object}")}
            ),
            "device2": NotConnectedError(
                {"sig": TypeError(f"Can't make converter for {object}")}
            ),
        }
    )
    assert str(expected_output) == str(exc.value)


def test_introspecting_sub_errors():
    sub_error1 = NotConnectedError("bad")
    assert sub_error1.sub_errors == {}
    sub_error2 = ValueError("very bad")
    error = NotConnectedError({"child1": sub_error1, "child2": sub_error2})
    assert error.sub_errors == {"child1": sub_error1, "child2": sub_error2}


async def test_error_handling_init_devices(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnectedError) as exc:
        # flake8: noqa
        async with init_devices(timeout=0.1):
            dummy_device_two_working_one_timeout_two_value_error = (
                DummyDeviceTwoWorkingTwoTimeOutTwoValueError()
            )
            dummy_device_one_working_one_timeout = DummyDeviceOneWorkingOneTimeout()

    expected_output = NotConnectedError(
        {
            "dummy_device_two_working_one_timeout_two_value_error": (
                TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT
            ),
            "dummy_device_one_working_one_timeout": ONE_WORKING_ONE_TIMEOUT_OUTPUT,
        }
    )
    assert str(expected_output) == str(exc.value)

    logs = caplog.get_records("call")
    logs = [
        log
        for log in logs
        if "ophyd_async" in log.pathname and "_signal" not in log.pathname
    ]
    assert len(logs) == 5
    assert (
        logs[0].message
        == logs[1].message
        == "device `value_error_signal` raised unexpected exception ValueError"
    )
    assert logs[0].levelname == logs[1].levelname == "ERROR"

    assert logs[2].levelname == "DEBUG"
    assert logs[3].levelname == "DEBUG"
    # These messages could come in any order
    messages = [logs[idx].message for idx in (2, 3)]
    for protocol in ("pva", "ca"):
        assert f"signal {protocol}://A_NON_EXISTENT_SIGNAL timed out" in messages


def test_not_connected_error_output():
    assert str(TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT) == (
        "\ntimeout_child_device_ca: NotConnectedError:\n"
        "    timeout_signal: NotConnectedError: ca://A_NON_EXISTENT_SIGNAL\n"
        "timeout_child_device_pva: NotConnectedError:\n"
        "    timeout_signal: NotConnectedError: pva://A_NON_EXISTENT_SIGNAL\n"
        "value_error_child_device1: NotConnectedError:\n"
        "    value_error_signal: ValueError: Some ValueError text\n"
        "value_error_child_device2: NotConnectedError:\n"
        "    value_error_signal: ValueError\n"
    )


@pytest.mark.asyncio
async def test_merge_gathered_dicts_raises_for_duplicate_keys():
    with pytest.raises(
        ValueError, match="Duplicate keys found while merging dictionaries"
    ) as exc:
        await merge_gathered_dicts(
            [
                asyncio.sleep(0, result={"a": 1}),
                asyncio.sleep(0, result={"a": 2}),
                asyncio.sleep(0, result={"b": 3}),
                asyncio.sleep(0, result={"c": 4}),
                asyncio.sleep(0, result={"c": 5}),
            ]
        )

    assert "a, c" in str(exc.value)


@pytest.mark.asyncio
async def test_merge_gathered_dicts_raises_for_blank_duplicate_keys_message():
    with pytest.raises(ValueError, match="Have you remembered to name the Device"):
        await merge_gathered_dicts(
            [
                asyncio.sleep(0, result={"": 1}),
                asyncio.sleep(0, result={"": 2}),
            ]
        )


async def test_combining_top_level_signal_and_child_device():
    dummy_device1 = DummyDeviceCombiningTopLevelSignalAndSubDevice()
    with pytest.raises(NotConnectedError) as exc:
        await dummy_device1.connect(timeout=0.01)
    assert str(exc.value) == (
        "\ntimeout_signal: NotConnectedError: ca://A_NON_EXISTENT_SIGNAL\n"
        "sub_device: NotConnectedError:\n"
        "    value_error_signal: ValueError: Some ValueError text\n"
    )

    with pytest.raises(NotConnectedError) as exc:
        async with init_devices(timeout=0.1):
            dummy_device2 = DummyDeviceCombiningTopLevelSignalAndSubDevice()
    assert str(exc.value) == (
        "\ndummy_device2: NotConnectedError:\n"
        "    timeout_signal: NotConnectedError: ca://A_NON_EXISTENT_SIGNAL\n"
        "    sub_device: NotConnectedError:\n"
        "        value_error_signal: ValueError: Some ValueError text\n"
    )


async def test_format_error_string_input():
    with pytest.raises(
        RuntimeError,
        match=("Unexpected type `<class 'int'>` expected `str` or `dict`"),
    ):
        not_connected = NotConnectedError(123)
        str(not_connected)

    with pytest.raises(
        RuntimeError, match=("Unexpected type `<class 'int'>`, expected an Exception")
    ):
        not_connected = NotConnectedError({"test": 123})
        str(not_connected)


def test_core_notconnected_emits_deprecation_warning():
    with pytest.deprecated_call():
        from ophyd_async.core import NotConnected  # noqa: F401


async def _async_value(val: T) -> T:
    """Helper function to create an awaitable that returns a value."""
    return val


async def test_gather_dict_empty():
    """Test gather_dict with an empty dictionary."""
    result = await gather_dict({})
    assert result == {}


async def test_gather_dict_awaits_values_and_infers_types():
    """Test gather_dict keeps keys and order, and types the result without hints."""
    result = await gather_dict(
        {"a": _async_value(1), "b": _async_value(2), "c": _async_value(3)}
    )
    assert_type(result, dict[str, int])
    assert result == {"a": 1, "b": 2, "c": 3}
    assert list(result) == ["a", "b", "c"]


async def test_gather_dict_infers_array_values():
    """Test gather_dict types ndarray results, which the old signature got wrong."""

    async def get_array(n: int) -> np.ndarray:
        return np.zeros(n)

    result = await gather_dict({k: get_array(n) for k, n in (("a", 1), ("b", 2))})
    assert_type(result, dict[str, np.ndarray])
    assert list(result) == ["a", "b"]


# Cancellation propagation is broken in asyncio.gather on Python 3.10, so the exception
# with the message is not reachable via the __cause__ chain however you will still get
# the message in the stack trace
@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="https://github.com/python/cpython/issues/112534"
)
@pytest.mark.parametrize(
    "set_to_delay, expected_message, expected_results",
    # Test cases for different things taking too long
    [
        # plain awaitable (currently not handled)
        [
            "x",
            None,
            None,
        ],
        # Device with a custom set() method
        ["y", "CancelledError while awaiting .* on my_device", None],
        # Task wrapping an async function (currently not handled)
        ["z", None, None],
        # Setting a Motor on a Device
        ["omega", "BL03I-MO-OMEGA", None],
        # Everything completes successfully in a timely fashion
        [None, None, [1, None, 1, None]],
    ],
)
async def test_cancelled_error_message_for_gather_is_populated_on_timeout(
    set_to_delay: str, expected_message: str, expected_results: list
):
    async def async_func(name: str, value: int) -> int:
        if set_to_delay == name:
            await asyncio.sleep(20)
        return value

    plain_awaitable = async_func("x", 1)

    class GenericDevice(Device):
        def __init__(self, name):
            super().__init__(name)

        @AsyncStatus.wrap
        async def set(self, value: int):
            await async_func("y", value)

    class MotorDevice(Device):
        def __init__(self, name):
            self.omega = Motor("BL03I-MO-OMEGA")
            super().__init__(name)

        async def set_omega(self, value: int, *args, **kwargs):
            await async_func("omega", value)

    async_status_device = GenericDevice("my_device")
    task_wrapped = asyncio.create_task(async_func("z", 1), name="set z")
    motor_device = MotorDevice("my_motor_device")
    await motor_device.connect(mock=True)
    _patch_motor(motor_device.omega)
    callback_on_mock_put(motor_device.omega.user_setpoint, motor_device.set_omega)

    gather_awaitable = asyncio.gather(
        plain_awaitable,
        async_status_device.set(1),
        task_wrapped,
        motor_device.omega.set(1),
    )
    if set_to_delay:
        with pytest.raises(asyncio.TimeoutError) as exc_info:
            await asyncio.wait_for(gather_awaitable, timeout=0.1)
        cause = exc_info.value.__cause__
        assert isinstance(cause, CancelledError)
        assert _contains_message(cause, expected_message)
    else:
        results = await gather_awaitable
        assert results == expected_results


def _contains_message(e: BaseException, expected_message: str) -> bool:
    return (
        expected_message is None
        or (e.args and re.search(expected_message, e.args[0]))
        or (e.__cause__ and _contains_message(e.__cause__, expected_message))
    )


def _patch_motor(motor: Motor, initial_position=0):
    set_mock_value(motor.user_setpoint, initial_position)
    set_mock_value(motor.user_readback, initial_position)
    set_mock_value(motor.deadband, 0.001)
    set_mock_value(motor.motor_done_move, 1)
    set_mock_value(motor.velocity, 3)
    set_mock_value(motor.max_velocity, 5)
    set_mock_value(motor.high_limit_travel, float("inf"))
    set_mock_value(motor.low_limit_travel, float("-inf"))


@pytest.mark.parametrize(
    "acceleration_time",
    [
        0.05,
        # No ramp at all, which used to make the last position NaN
        0,
    ],
)
async def test_simulate_move_ends_at_target(acceleration_time: float):
    positions = [p async for p in simulate_move(0, 1.5, 10, acceleration_time)]
    assert positions[-1] == 1.5
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "datatype, dtype",
    [
        (Array1D[np.int8], np.dtype(np.int8)),
        # From NumPy 2.5 on Python 3.12+ this is a `type` alias, not an `np.ndarray`
        (npt.NDArray[np.float64], np.dtype(np.float64)),
    ],
)
def test_get_dtype(datatype, dtype):
    assert get_dtype(datatype) == dtype


@pytest.mark.parametrize(
    "datatype",
    # Deliberately invalid, as Array1D and NDArray only accept numpy scalar types
    [Array1D[MyEnum], npt.NDArray[MyEnum]],  # pyright: ignore[reportInvalidTypeForm]
)
def test_get_dtype_raises_for_element_type_without_numpy_dtype(datatype):
    with pytest.raises(TypeError, match="has no numpy dtype"):
        get_dtype(datatype)


@pytest.mark.parametrize(
    "annotation, origin",
    [
        (npt.NDArray[np.float64], np.ndarray),
        (Array1D[np.float64], np.ndarray),
        (Sequence[str], Sequence),
        (int, None),
    ],
)
def test_get_unaliased_origin(annotation, origin):
    assert get_unaliased_origin(annotation) is origin


class StuckPutBackend(SoftSignalBackend):
    """A put that never finishes, and may fail while being cancelled."""

    def __init__(self, cleanup_error: Exception | None):
        self.cleanup_error = cleanup_error
        super().__init__(datatype=int)

    async def put(self, value: int | None) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if self.cleanup_error is not None:
                raise self.cleanup_error from None
            raise


@pytest.mark.parametrize(
    "cleanup_error, expected",
    [(None, TimeoutError), (ValueError("cleanup failed"), ValueError)],
)
async def test_a_timed_out_put_raises_the_error_its_cancellation_raised(
    cleanup_error: Exception | None, expected: type[Exception]
):
    loop = asyncio.get_running_loop()
    unhandled = []
    loop.set_exception_handler(lambda _, context: unhandled.append(context))
    signal = SignalRW(StuckPutBackend(cleanup_error), name="sig")
    await signal.connect()

    with pytest.raises(expected):
        await signal.set(1, timeout=0.01)

    # The error was retrieved, not left for the loop to log
    gc.collect()
    await asyncio.sleep(0)
    loop.set_exception_handler(None)
    assert unhandled == []


async def test_a_cancelled_wait_for_leaves_no_unretrieved_error():
    loop = asyncio.get_running_loop()
    unhandled = []
    loop.set_exception_handler(lambda _, context: unhandled.append(context))

    async def fails_when_cancelled():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ValueError("cleanup failed") from None

    outer = asyncio.create_task(_wait_for(fails_when_cancelled(), 10, "source"))
    await asyncio.sleep(0.01)
    outer.cancel()
    # The error raised while ending the cancelled work shows through
    with pytest.raises(ValueError, match="cleanup failed"):
        await outer

    gc.collect()
    await asyncio.sleep(0)
    loop.set_exception_handler(None)
    assert unhandled == []


async def test_wait_for_returns_the_result_with_and_without_a_timeout():
    async def value():
        await asyncio.sleep(0)
        return 42

    assert await _wait_for(value(), 5, "source") == 42
    assert await _wait_for(value(), None, "source") == 42


async def test_wait_for_expiry_raises_timeout_error_naming_the_source():
    with pytest.raises(TimeoutError, match="^source$"):
        await _wait_for(asyncio.sleep(1), 0.01, "source")


async def test_wait_for_relabels_a_timeout_error_from_the_coroutine():
    async def inner():
        raise TimeoutError("inner")

    with pytest.raises(TimeoutError, match="^source$") as exc_info:
        await _wait_for(inner(), 5, "source")
    assert str(exc_info.value.__cause__) == "inner"


async def test_wait_for_does_not_swallow_a_cancel_arriving_as_the_work_finishes():
    finished = asyncio.get_running_loop().create_future()

    async def inner():
        return await finished

    outer = asyncio.create_task(_wait_for(inner(), 5, "source"))
    await asyncio.sleep(0)
    finished.set_result(1)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer


async def test_wait_for_shows_an_error_raised_while_being_cancelled():
    async def inner():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise ValueError("cleanup") from None

    with pytest.raises(ValueError, match="cleanup"):
        await _wait_for(inner(), 0.01, "source")


async def test_wait_for_expiry_and_an_outside_cancel_is_a_cancel():
    outer = asyncio.create_task(_wait_for(asyncio.sleep(1), 0.05, "source"))
    await asyncio.sleep(0.05)  # About when the timeout expires
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer


async def test_wait_for_expiry_after_a_swallowed_cancel_is_still_a_timeout_error():
    async def body():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass  # Swallowed without uncancel()
        await _wait_for(asyncio.sleep(1), 0.01, "source")

    task = asyncio.create_task(body())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(TimeoutError, match="^source$"):
        await task


async def _raise_on_cancel(
    error: Exception | None, cleanup_time: float, cancelled: asyncio.Event
) -> None:
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        cancelled.set()
        await asyncio.sleep(cleanup_time)
        if error is not None:
            raise error from None
        raise


@pytest.mark.parametrize(
    "errors, raised",
    [
        ([None, None], None),
        ([None, ValueError()], ValueError),
        # The first task in the order given wins, though it ends last
        ([ValueError(), RuntimeError()], ValueError),
    ],
)
async def test_cancel_and_wait_waits_for_every_task_then_raises_the_first_error(
    errors: list[Exception | None], raised: type[Exception] | None
):
    cleanup_times = [0.02, 0.0]
    tasks = [
        asyncio.create_task(_raise_on_cancel(error, cleanup_time, asyncio.Event()))
        for error, cleanup_time in zip(errors, cleanup_times, strict=True)
    ]
    await asyncio.sleep(0)  # let the tasks start
    expectation = pytest.raises(raised) if raised else nullcontext()
    with expectation:
        await cancel_and_wait(*tasks)
    assert all(task.done() for task in tasks)


@pytest.mark.parametrize("caller_cancels", [1, 2])
async def test_cancel_and_wait_cancelled_caller_waits_then_raises_its_cancel(
    caller_cancels: int,
):
    loop = asyncio.get_running_loop()
    unhandled: list[str] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: unhandled.append(context["message"]))
    try:
        cancelled = asyncio.Event()
        task = asyncio.create_task(_raise_on_cancel(ValueError(), 0.02, cancelled))
        await asyncio.sleep(0)  # let the task start
        caller = asyncio.create_task(cancel_and_wait(task))
        await cancelled.wait()
        for _ in range(caller_cancels):
            caller.cancel()
            await asyncio.sleep(0)
        await asyncio.wait([caller])
        assert caller.cancelled()
        assert task.done()
        # A task whose error was never retrieved logs it when collected
        del task, caller
        gc.collect()
    finally:
        loop.set_exception_handler(old_handler)
    assert unhandled == []
