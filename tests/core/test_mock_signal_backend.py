import asyncio
import re
from itertools import repeat
from unittest.mock import ANY, AsyncMock, MagicMock, call

import pytest

from ophyd_async.core import (
    Device,
    DeviceCollector,
    MockSignalBackend,
    SignalRW,
    SignalW,
    SoftSignalBackend,
    callback_on_mock_put,
    get_mock_put,
    mock_puts_blocked,
    reset_mock_put_calls,
    set_mock_put_proceeds,
    set_mock_value,
    set_mock_values,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


@pytest.mark.parametrize("connect_mock_mode", [True, False])
async def test_mock_signal_backend(connect_mock_mode):
    mock_signal = SignalRW(MockSignalBackend(datatype=str))
    # If mock is false it will be handled like a normal signal, otherwise it will
    # initalize a new backend from the one in the line above
    await mock_signal.connect(mock=connect_mock_mode)
    assert isinstance(mock_signal._backend, MockSignalBackend)

    assert await mock_signal._backend.get_value() == ""
    await mock_signal._backend.put("test")
    assert await mock_signal._backend.get_value() == "test"
    assert mock_signal._backend.put_mock.call_args_list == [
        call("test", wait=True, timeout=None),
    ]


@pytest.mark.parametrize("epics_protocol", ["ca", "pva"])
async def test_mock_signal_backend_source(epics_protocol):
    mock_signal_rw = epics_signal_rw(
        str,
        f"{epics_protocol}://READ_PV",
        f"{epics_protocol}://WRITE_PV",
        name="mock_name",
    )
    mock_signal_r = epics_signal_r(
        str,
        f"{epics_protocol}://READ_PV",
        name="mock_name",
    )
    await mock_signal_rw.connect(mock=True)
    await mock_signal_r.connect(mock=True)

    assert mock_signal_rw.source == f"mock+{epics_protocol}://READ_PV"
    assert mock_signal_r.source == f"mock+{epics_protocol}://READ_PV"


async def test_set_mock_value():
    mock_signal = SignalRW(SoftSignalBackend(int))
    await mock_signal.connect(mock=True)
    assert await mock_signal.get_value() == 0
    assert mock_signal._backend
    assert await mock_signal._backend.get_value() == 0
    set_mock_value(mock_signal, 10)
    assert await mock_signal.get_value() == 10
    assert await mock_signal._backend.get_value() == 10


async def test_set_mock_put_proceeds():
    mock_signal = SignalW(SoftSignalBackend(str))
    await mock_signal.connect(mock=True)

    assert isinstance(mock_signal._backend, MockSignalBackend)

    assert mock_signal._backend.put_proceeds.is_set() is True

    set_mock_put_proceeds(mock_signal, False)
    assert mock_signal._backend.put_proceeds.is_set() is False
    set_mock_put_proceeds(mock_signal, True)
    assert mock_signal._backend.put_proceeds.is_set() is True


async def test_set_mock_put_proceeds_timeout():
    mock_signal = SignalRW(SoftSignalBackend(str))
    await mock_signal.connect(mock=True)

    set_mock_put_proceeds(mock_signal, False)

    with pytest.raises(asyncio.exceptions.TimeoutError):
        await mock_signal.set("test", wait=True, timeout=1)


async def test_put_proceeds_timeout():
    mock_signal = SignalW(SoftSignalBackend(str))
    await mock_signal.connect(mock=True)
    assert isinstance(mock_signal._backend, MockSignalBackend)

    assert mock_signal._backend.put_proceeds.is_set() is True

    set_mock_put_proceeds(mock_signal, False)
    assert mock_signal._backend.put_proceeds.is_set() is False
    set_mock_put_proceeds(mock_signal, True)
    assert mock_signal._backend.put_proceeds.is_set() is True


async def test_mock_utils_throw_error_if_backend_isnt_mock_signal_backend():
    signal = SignalRW(SoftSignalBackend(int))

    exc_msgs = []
    with pytest.raises(AssertionError) as exc:
        set_mock_value(signal, 10)
    exc_msgs.append(str(exc.value))
    with pytest.raises(AssertionError) as exc:
        get_mock_put(signal).assert_called_once_with(10)
    exc_msgs.append(str(exc.value))
    with pytest.raises(AssertionError) as exc:
        async with mock_puts_blocked(signal):
            ...
    exc_msgs.append(str(exc.value))
    with pytest.raises(AssertionError) as exc:
        with callback_on_mock_put(signal, lambda x: _):
            ...
    exc_msgs.append(str(exc.value))
    with pytest.raises(AssertionError) as exc:
        set_mock_put_proceeds(signal, False)
    exc_msgs.append(str(exc.value))
    with pytest.raises(AssertionError) as exc:
        for _ in set_mock_values(signal, [10]):
            ...
    exc_msgs.append(str(exc.value))

    for msg in exc_msgs:
        assert msg == (
            "Expected to receive a `MockSignalBackend`, instead "
            f" received {SoftSignalBackend}. "
        )


async def test_get_mock_put():
    mock_signal = epics_signal_rw(str, "READ_PV", "WRITE_PV", name="mock_name")
    await mock_signal.connect(mock=True)
    await mock_signal.set("test_value", wait=True, timeout=100)

    mock = get_mock_put(mock_signal)
    mock.assert_called_once_with("test_value", wait=True, timeout=100)

    def err_text(text, wait, timeout):
        return (
            f"Expected: put('{re.escape(str(text))}', wait={re.escape(str(wait))},"
            f" timeout={re.escape(str(timeout))})",
            "Actual: put('test_value', wait=True, timeout=100)",
        )

    for text, wait, timeout in [
        ("wrong_name", True, 100),  # name wrong
        ("test_value", False, 100),  # wait wrong
        ("test_value", True, 0),  # timeout wrong
        ("test_value", False, 0),  # wait and timeout wrong
    ]:
        with pytest.raises(AssertionError) as exc:
            mock.assert_called_once_with(text, wait=wait, timeout=timeout)
        for err_substr in err_text(text, wait, timeout):
            assert err_substr in str(exc.value)


@pytest.fixture
async def mock_signals():
    async with DeviceCollector(mock=True):
        signal1 = epics_signal_rw(str, "READ_PV1", "WRITE_PV1", name="mock_name1")
        signal2 = epics_signal_rw(str, "READ_PV2", "WRITE_PV2", name="mock_name2")

    await signal1.set("first_value", wait=True, timeout=1)
    await signal2.set("first_value", wait=True, timeout=1)
    assert await signal1.get_value() == "first_value"
    assert await signal2.get_value() == "first_value"
    return signal1, signal2


async def test_blocks_during_put(mock_signals):
    signal1, signal2 = mock_signals

    async with mock_puts_blocked(signal1, signal2):
        status1 = signal1.set("second_value", wait=True, timeout=1)
        status2 = signal2.set("second_value", wait=True, timeout=1)
        assert await signal1.get_value() == "second_value"
        assert await signal2.get_value() == "second_value"
        assert not status1.done
        assert not status2.done

    await asyncio.sleep(1e-4)

    assert status1.done
    assert status2.done
    assert await signal1._backend.get_value() == "second_value"
    assert await signal2._backend.get_value() == "second_value"


async def test_callback_on_mock_put_as_context_manager(mock_signals):
    signal1_callbacks = MagicMock()
    signal2_callbacks = MagicMock()
    signal1, signal2 = mock_signals
    with callback_on_mock_put(signal1, signal1_callbacks):
        await signal1.set("second_value", wait=True, timeout=1)
    with callback_on_mock_put(signal2, signal2_callbacks):
        await signal2.set("second_value", wait=True, timeout=1)

    signal1_callbacks.assert_called_once_with("second_value", wait=True, timeout=1)
    signal2_callbacks.assert_called_once_with("second_value", wait=True, timeout=1)


async def test_callback_on_mock_put_not_as_context_manager():
    mock_signal = SignalRW(SoftSignalBackend(float))
    await mock_signal.connect(mock=True)
    calls = []
    callback_on_mock_put(
        mock_signal, lambda *args, **kwargs: calls.append({**kwargs, "_args": args})
    )
    await mock_signal.set(10.0)
    assert calls == [
        {
            "_args": (10.0,),
            "timeout": 10.0,
            "wait": True,
        }
    ]


async def test_async_callback_on_mock_put(mock_signals):
    signal1_callbacks = AsyncMock()
    signal2_callbacks = AsyncMock()
    signal1, signal2 = mock_signals
    with callback_on_mock_put(signal1, signal1_callbacks):
        await signal1.set("second_value", wait=True, timeout=1)
    with callback_on_mock_put(signal2, signal2_callbacks):
        await signal2.set("second_value", wait=True, timeout=1)

    signal1_callbacks.assert_awaited_once_with("second_value", wait=True, timeout=1)
    signal2_callbacks.assert_awaited_once_with("second_value", wait=True, timeout=1)


async def test_callback_on_mock_put_fails_if_args_are_not_correct():
    mock_signal = SignalRW(SoftSignalBackend(float))
    await mock_signal.connect(mock=True)

    def some_function_without_kwargs(arg):
        pass

    callback_on_mock_put(mock_signal, some_function_without_kwargs)
    with pytest.raises(TypeError) as exc:
        await mock_signal.set(10.0)
    assert str(exc.value).endswith(
        "some_function_without_kwargs() got an unexpected keyword argument 'wait'"
    )


async def test_set_mock_values(mock_signals):
    signal1, signal2 = mock_signals

    assert await signal2.get_value() == "first_value"
    for value_set in set_mock_values(signal1, ["second_value", "third_value"]):
        assert await signal1.get_value() == value_set

    iterator = set_mock_values(signal2, ["second_value", "third_value"])
    assert await signal2.get_value() == "first_value"
    next(iterator)
    assert await signal2.get_value() == "second_value"
    next(iterator)
    assert await signal2.get_value() == "third_value"


async def test_set_mock_values_exhausted_passes(mock_signals):
    signal1, signal2 = mock_signals
    for value_set in set_mock_values(
        signal1, ["second_value", "third_value"], require_all_consumed=True
    ):
        assert await signal1.get_value() == value_set

    iterator = set_mock_values(
        signal2,
        repeat(iter(["second_value", "third_value"]), 6),
        require_all_consumed=False,
    )
    calls = 0
    for calls, value_set in enumerate(iterator, start=1):  # noqa: B007
        assert await signal2.get_value() == value_set

    assert calls == 6


async def test_set_mock_values_exhausted_fails(mock_signals):
    signal1, signal2 = mock_signals

    for value_set in (
        iterator := set_mock_values(
            signal1, ["second_value", "third_value"], require_all_consumed=True
        )
    ):
        assert await signal1.get_value() == value_set
        break

    with pytest.raises(AssertionError):
        iterator.__del__()

    # Set so it doesn't raise the same error on teardown
    iterator.require_all_consumed = False


async def test_reset_mock_put_calls(mock_signals):
    signal1, signal2 = mock_signals
    await signal1.set("test_value", wait=True, timeout=1)
    get_mock_put(signal1).assert_called_with("test_value", wait=ANY, timeout=ANY)
    reset_mock_put_calls(signal1)
    with pytest.raises(AssertionError) as exc:
        get_mock_put(signal1).assert_called_with("test_value", wait=ANY, timeout=ANY)
    # Replacing spaces because they change between runners
    # (e.g the github actions runner has more)
    assert str(exc.value).replace(" ", "").replace("\n", "") == (
        "expectedcallnotfound."
        "Expected:put('test_value',wait=<ANY>,timeout=<ANY>)"
        "Actual:notcalled."
    )


async def test_mock_signal_of_soft_signal_backend_receives_intial_value():
    class SomeDevice(Device):
        def __init__(self, name):
            self.my_signal = soft_signal_rw(
                datatype=int,
                initial_value=10,
                name=name,
            )

    mocked_device = SomeDevice("mocked_device")
    await mocked_device.connect(mock=True)
    soft_device = SomeDevice("soft_device")
    await soft_device.connect(mock=False)

    assert await mocked_device.my_signal.get_value() == 10
    assert await soft_device.my_signal.get_value() == 10


async def test_mock_signal_of_soft_signal_backend_receives_metadata():
    class SomeDevice(Device):
        def __init__(self, name):
            self.my_signal = soft_signal_rw(
                datatype=float, initial_value=1.0, name=name, units="mm", precision=2
            )

    mocked_device = SomeDevice("mocked_device")
    await mocked_device.connect(mock=True)
    soft_device = SomeDevice("soft_device")
    await soft_device.connect(mock=False)

    assert await mocked_device.my_signal.describe() == {
        "mocked_device": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+soft://mocked_device",
            "units": "mm",
            "precision": 2,
        }
    }
    assert await soft_device.my_signal.describe() == {
        "soft_device": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "soft://soft_device",
            "units": "mm",
            "precision": 2,
        }
    }


async def test_writing_to_soft_signals_in_mock():
    class MyDevice(Device):
        def __init__(self, prefix: str, name: str = ""):
            self.signal, self.backend_put = soft_signal_r_and_setter(int)

        async def set(self):
            self.backend_put(1)

    device = MyDevice("-SOME-PREFIX", name="my_device")
    await device.connect(mock=True)
    assert await device.signal.get_value() == 0
    await device.set()
    assert await device.signal.get_value() == 1

    signal, backend_put = soft_signal_r_and_setter(int)
    await signal.connect(mock=False)
    assert await signal.get_value() == 0
    backend_put(100)
    assert await signal.get_value() == 100


async def test_when_put_mock_called_with_typo_then_fails_but_calling_directly_passes():
    mock_signal = SignalRW(SoftSignalBackend(int))
    await mock_signal.connect(mock=True)
    assert isinstance(mock_signal._backend, MockSignalBackend)
    mock = mock_signal._backend.put_mock
    with pytest.raises(AttributeError):
        mock.asssert_called_once()  # Note typo here is deliberate!
    await mock()
