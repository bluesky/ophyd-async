from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    MockSignalBackend,
    NotConnected,
    SignalRW,
)
from ophyd_async.epics.signal import epics_signal_rw


class ValueErrorBackend(MockSignalBackend):
    def __init__(self, exc_text=""):
        self.exc_text = exc_text
        super().__init__(datatype=int, initial_backend=None)

    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        raise ValueError(self.exc_text)


class WorkingDummyChildDevice(Device):
    def __init__(self, name: str = "working_dummy_child_device") -> None:
        self.working_signal = SignalRW(backend=MockSignalBackend(datatype=int))
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
        self.value_error_signal = SignalRW(backend=ValueErrorBackend(exc_text=exc_text))
        super().__init__(name=name)


class DummyDeviceOneWorkingOneTimeout(Device):
    def __init__(self, name: str = "dummy_device_one_working_one_timeout") -> None:
        self.working_child_device = WorkingDummyChildDevice()
        self.timeout_child_device = TimeoutDummyChildDeviceCA()
        super().__init__(name=name)


ONE_WORKING_ONE_TIMEOUT_OUTPUT = NotConnected(
    {
        "timeout_child_device": NotConnected(
            {"timeout_signal": NotConnected("ca://A_NON_EXISTENT_SIGNAL")}
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


TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT = NotConnected(
    {
        "timeout_child_device_ca": NotConnected(
            {
                "timeout_signal": NotConnected("ca://A_NON_EXISTENT_SIGNAL"),
            }
        ),
        "timeout_child_device_pva": NotConnected(
            {"timeout_signal": NotConnected("pva://A_NON_EXISTENT_SIGNAL")}
        ),
        "value_error_child_device1": NotConnected(
            {"value_error_signal": ValueError("Some ValueError text")}
        ),
        "value_error_child_device2": NotConnected(
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
    with pytest.raises(NotConnected) as e:
        await dummy_device_one_working_one_timeout.connect(timeout=0.01)

    assert str(e.value) == str(ONE_WORKING_ONE_TIMEOUT_OUTPUT)

    logs = caplog.get_records("call")

    # See https://github.com/bluesky/ophyd-async/issues/519
    # assert len(logs) == 3

    assert "signal ca://A_NON_EXISTENT_SIGNAL timed out" == logs[-1].message
    assert logs[-1].levelname == "DEBUG"


async def test_error_handling_value_errors(caplog):
    """Checks that NotConnected is aggregated correctly across Devices."""

    caplog.set_level(10)

    dummy_device_two_working_one_timeout_two_value_error = (
        DummyDeviceTwoWorkingTwoTimeOutTwoValueError("dsf")
    )

    # This should fail since the error is a ValueError
    with pytest.raises(NotConnected) as e:
        (
            await dummy_device_two_working_one_timeout_two_value_error.connect(
                timeout=0.01
            ),
        )
    assert str(e.value) == str(TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT)

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


async def test_error_handling_device_collector(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected) as e:
        # flake8: noqa
        async with DeviceCollector(timeout=0.1):
            dummy_device_two_working_one_timeout_two_value_error = (
                DummyDeviceTwoWorkingTwoTimeOutTwoValueError()
            )
            dummy_device_one_working_one_timeout = DummyDeviceOneWorkingOneTimeout()

    expected_output = NotConnected(
        {
            "dummy_device_two_working_one_timeout_two_value_error": (
                TWO_WORKING_TWO_TIMEOUT_TWO_VALUE_ERROR_OUTPUT
            ),
            "dummy_device_one_working_one_timeout": ONE_WORKING_ONE_TIMEOUT_OUTPUT,
        }
    )
    assert str(expected_output) == str(e.value)

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
        "\ntimeout_child_device_ca: NotConnected:\n"
        "    timeout_signal: NotConnected: ca://A_NON_EXISTENT_SIGNAL\n"
        "timeout_child_device_pva: NotConnected:\n"
        "    timeout_signal: NotConnected: pva://A_NON_EXISTENT_SIGNAL\n"
        "value_error_child_device1: NotConnected:\n"
        "    value_error_signal: ValueError: Some ValueError text\n"
        "value_error_child_device2: NotConnected:\n"
        "    value_error_signal: ValueError\n"
    )


async def test_combining_top_level_signal_and_child_device():
    dummy_device1 = DummyDeviceCombiningTopLevelSignalAndSubDevice()
    with pytest.raises(NotConnected) as e:
        await dummy_device1.connect(timeout=0.01)
    assert str(e.value) == (
        "\ntimeout_signal: NotConnected: ca://A_NON_EXISTENT_SIGNAL\n"
        "sub_device: NotConnected:\n"
        "    value_error_signal: ValueError: Some ValueError text\n"
    )

    with pytest.raises(NotConnected) as e:
        async with DeviceCollector(timeout=0.1):
            dummy_device2 = DummyDeviceCombiningTopLevelSignalAndSubDevice()
    assert str(e.value) == (
        "\ndummy_device2: NotConnected:\n"
        "    timeout_signal: NotConnected: ca://A_NON_EXISTENT_SIGNAL\n"
        "    sub_device: NotConnected:\n"
        "        value_error_signal: ValueError: Some ValueError text\n"
    )


async def test_format_error_string_input():
    with pytest.raises(
        RuntimeError,
        match=("Unexpected type `<class 'int'>` " "expected `str` or `dict`"),
    ):
        not_connected = NotConnected(123)
        str(not_connected)

    with pytest.raises(
        RuntimeError, match=("Unexpected type `<class 'int'>`, expected an Exception")
    ):
        not_connected = NotConnected({"test": 123})
        str(not_connected)
