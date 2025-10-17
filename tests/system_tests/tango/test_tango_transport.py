import asyncio
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from tango import AttrDataFormat, CmdArgType, DevState
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import (
    AsyncioExecutor,
    get_global_executor,
)
from test_base_device import TestDevice
from test_tango_signals import make_backend

from ophyd_async.core import (
    Array1D,
    NotConnectedError,
    StrictEnum,
)
from ophyd_async.tango.core import (
    AttributeProxy,
    CommandProxy,
    TangoDoubleStringTable,
    TangoLongStringTable,
    TangoSignalBackend,
    ensure_proper_executor,
    get_dtype_extended,
    get_full_attr_trl,
    get_python_type,
    get_tango_trl,
    try_to_cast_as_float,
)
from ophyd_async.tango.testing import TestConfig


# --------------------------------------------------------------------
async def prepare_device(trl: str, pv: str, put_value: Any) -> None:
    proxy = await DeviceProxy(trl)
    setattr(proxy, pv, put_value)


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device(subprocess_helper):
    with subprocess_helper(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}]
    ) as context:
        yield context.trls["test/device/1"]


# --------------------------------------------------------------------
class HelperClass:
    @ensure_proper_executor
    async def mock_func(self):
        return "executed"


# Test function
@pytest.mark.asyncio
async def test_ensure_proper_executor():
    # Instantiate the helper class and call the decorated method
    helper_instance = HelperClass()
    result = await helper_instance.mock_func()

    # Assertions
    assert result == "executed"
    assert isinstance(get_global_executor(), AsyncioExecutor)


# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "tango_type, tango_format, expected",
    [
        # Scalar types
        (CmdArgType.DevVoid, AttrDataFormat.SCALAR, None),
        (CmdArgType.DevBoolean, AttrDataFormat.SCALAR, bool),
        (CmdArgType.DevShort, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevLong, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevLong64, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevFloat, AttrDataFormat.SCALAR, float),
        (CmdArgType.DevDouble, AttrDataFormat.SCALAR, float),
        (CmdArgType.DevUShort, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevULong, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevULong64, AttrDataFormat.SCALAR, int),
        (CmdArgType.DevString, AttrDataFormat.SCALAR, str),
        (CmdArgType.DevEncoded, AttrDataFormat.SCALAR, str),
        (CmdArgType.DevEnum, AttrDataFormat.SCALAR, StrictEnum),
        (CmdArgType.DevState, AttrDataFormat.SCALAR, StrictEnum),
        (CmdArgType.ConstDevString, AttrDataFormat.SCALAR, str),
        (CmdArgType.DevVarBooleanArray, AttrDataFormat.SCALAR, bool),
        (CmdArgType.DevUChar, AttrDataFormat.SCALAR, int),
        # Array types
        (CmdArgType.DevVarCharArray, AttrDataFormat.SPECTRUM, Sequence[str]),
        (CmdArgType.DevVarShortArray, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarShortArray, AttrDataFormat.IMAGE, npt.NDArray[int]),
        (CmdArgType.DevVarLongArray, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarLongArray, AttrDataFormat.IMAGE, npt.NDArray[int]),
        (CmdArgType.DevVarFloatArray, AttrDataFormat.SPECTRUM, Array1D[float]),
        (CmdArgType.DevVarFloatArray, AttrDataFormat.IMAGE, npt.NDArray[float]),
        (CmdArgType.DevVarDoubleArray, AttrDataFormat.SPECTRUM, Array1D[float]),
        (CmdArgType.DevVarDoubleArray, AttrDataFormat.IMAGE, npt.NDArray[float]),
        (CmdArgType.DevVarUShortArray, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarUShortArray, AttrDataFormat.IMAGE, npt.NDArray[int]),
        (CmdArgType.DevVarULongArray, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarULongArray, AttrDataFormat.IMAGE, npt.NDArray[int]),
        (CmdArgType.DevVarLong64Array, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarLong64Array, AttrDataFormat.IMAGE, npt.NDArray[int]),
        (CmdArgType.DevVarULong64Array, AttrDataFormat.SPECTRUM, Array1D[int]),
        (CmdArgType.DevVarULong64Array, AttrDataFormat.IMAGE, npt.NDArray[int]),
        # String array types
        (CmdArgType.DevVarStringArray, AttrDataFormat.SPECTRUM, Sequence[str]),
        (CmdArgType.DevVarStringArray, AttrDataFormat.IMAGE, Sequence[Sequence[str]]),
        (
            CmdArgType.DevVarLongStringArray,
            AttrDataFormat.SPECTRUM,
            TangoLongStringTable,
        ),
        (
            CmdArgType.DevVarDoubleStringArray,
            AttrDataFormat.SPECTRUM,
            TangoDoubleStringTable,
        ),
        # Bad type
        (float, AttrDataFormat.SCALAR, (False, float, "number")),
        # Bad format
        (float, "bad_format", (False, float, "format")),
    ],
)
def test_get_python_type(tango_type, tango_format, expected):
    config = TestConfig()
    config.data_format = tango_format
    config.data_type = tango_type
    if tango_type is CmdArgType.DevEnum:
        config.enum_labels = ["A", "B", "C"]
        py_type = get_python_type(config)
        assert issubclass(py_type, StrictEnum)
        assert [e.name for e in py_type] == ["A", "B", "C"]
    elif tango_type is CmdArgType.DevState:
        py_type = get_python_type(config)
        assert issubclass(py_type, StrictEnum)
        assert [e.name for e in py_type] == list(DevState.names.keys())
    elif tango_type is not float:
        print(f"CONFIG: {config.data_type}, {config.data_format}")
        assert get_python_type(config) == expected
    else:
        if tango_format == "bad_format":
            with pytest.raises(TypeError) as exc_info:
                get_python_type(config)
            assert str(exc_info.value) == "Unknown TangoFormat"
            return
        # get_python_type should raise a TypeError
        with pytest.raises(TypeError) as exc_info:
            get_python_type(config)
        assert str(exc_info.value) == "Unknown TangoType: <class 'float'>"


# --------------------------------------------------------------------
def test_try_to_cast_as_float():
    # Test with a valid float value
    result = try_to_cast_as_float(3.14)
    assert result == 3.14

    # Test with a valid integer value
    result = try_to_cast_as_float(42)
    assert result == 42.0

    # Test with a string that can be converted to float
    result = try_to_cast_as_float("2.718")
    assert result == 2.718

    # Test with a string that cannot be converted to float
    result = try_to_cast_as_float("not_a_number")
    assert result is None


# --------------------------------------------------------------------
@pytest.mark.parametrize(
    "datatype, expected",
    [
        (npt.NDArray[np.float64], np.dtype("float64")),
        (npt.NDArray[np.int8], np.dtype("int8")),
        (npt.NDArray[np.uint8], np.dtype("uint8")),
        (npt.NDArray[np.int32], np.dtype("int32")),
        (npt.NDArray[np.int64], np.dtype("int64")),
        (npt.NDArray[np.uint16], np.dtype("uint16")),
        (npt.NDArray[np.uint32], np.dtype("uint32")),
        (npt.NDArray[np.uint64], np.dtype("uint64")),
        (npt.NDArray[np.bool_], np.dtype("bool")),
        (npt.NDArray[DevState], CmdArgType.DevState),
        (npt.NDArray[np.str_], np.dtype("str")),
        (npt.NDArray[np.float32], np.dtype("float32")),
        (npt.NDArray[np.complex64], np.dtype("complex64")),
        (npt.NDArray[np.complex128], np.dtype("complex128")),
    ],
)
def test_get_dtype_extended(datatype, expected):
    assert get_dtype_extended(datatype) == expected


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr_name, proxy_needed, expected_type, should_raise",
    [
        ("justvalue", True, AttributeProxy, False),
        ("justvalue", False, AttributeProxy, False),
        ("clear", True, CommandProxy, False),
        ("clear", False, CommandProxy, False),
        ("nonexistent", True, None, True),
    ],
)
@pytest.mark.timeout(10)
async def test_get_tango_trl(
    tango_test_device, attr_name, proxy_needed, expected_type, should_raise
):
    trl = get_full_attr_trl(tango_test_device, attr_name)
    assert re.match(
        r"tango://[a-zA-Z0-9\.-_:]*/test/device/1/" + attr_name + r"#dbase=no", trl
    )
    # tango_test_device is of form tango://127.0.0.1:<port>/test/device/1#dbase=no
    proxy = await DeviceProxy(tango_test_device) if proxy_needed else None
    if should_raise:
        with pytest.raises(RuntimeError):
            await get_tango_trl(trl, proxy, 1)
    else:
        await asyncio.sleep(0.1)
        result = await get_tango_trl(trl, proxy, 1)
        assert isinstance(result, expected_type)


# --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("attr", ["justvalue", "array"])
async def test_attribute_proxy_get(tango_test_device, attr):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    val = None
    val = await attr_proxy.get()
    assert val is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr",
    ["justvalue", "array"],
)
async def test_attribute_proxy_put(tango_test_device, attr):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    old_value = await attr_proxy.get()
    new_value = old_value + 1
    await attr_proxy.put(new_value)
    await asyncio.sleep(
        0.1
    )  # for some reason this is required otherwise justvalue fails???
    updated_value = await attr_proxy.get()
    if isinstance(new_value, np.ndarray):
        assert np.all(updated_value == new_value)
    else:
        assert updated_value == new_value


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_proxy_put_force_timeout(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "slow_attribute")
    with pytest.raises(TimeoutError) as exc_info:
        await attr_proxy.put(3.0, timeout=0.1)
    assert "Timeout" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_proxy_put_exceptions(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "raise_exception_attr")
    with pytest.raises(RuntimeError) as exc_info:
        await attr_proxy.put(3.0)
    assert "device failure" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr, new_value", [("justvalue", 10), ("array", np.array([[2, 3, 4], [5, 6, 7]]))]
)
@pytest.mark.timeout(4.7)
async def test_attribute_proxy_get_w_value(tango_test_device, attr, new_value):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    await attr_proxy.put(new_value)
    await asyncio.sleep(1.0)
    attr_proxy_value = await attr_proxy.get()
    if isinstance(new_value, np.ndarray):
        assert np.all(attr_proxy_value == new_value)
    else:
        assert attr_proxy_value == new_value


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_get_config(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "justvalue")
    config = await attr_proxy.get_config()
    assert config.writable is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_get_reading(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "justvalue")
    reading = await attr_proxy.get_reading()
    assert reading["value"] is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_has_subscription(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "justvalue")
    expected = bool(attr_proxy._callback)
    has_subscription = attr_proxy.has_subscription()
    assert has_subscription is expected


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_set_polling(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "justvalue")
    attr_proxy.set_polling(True, 0.1, 1, 0.1)
    assert attr_proxy._allow_polling
    assert attr_proxy._polling_period == 0.1
    assert attr_proxy._abs_change == 1
    assert attr_proxy._rel_change == 0.1
    attr_proxy.set_polling(False)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(3)
async def test_attribute_poll(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "floatvalue")
    attr_proxy.support_events = False

    def callback(reading):
        nonlocal val
        val = reading["value"]

    def bad_callback():
        pass

    # Test polling with absolute change
    val = None

    attr_proxy.set_polling(True, 0.1, 1, 1.0)
    attr_proxy.subscribe_callback(callback)
    current_value = await attr_proxy.get()
    new_value = current_value + 2
    await attr_proxy.put(new_value)
    polling_period = attr_proxy._polling_period
    await asyncio.sleep(polling_period)
    assert val is not None
    attr_proxy.unsubscribe_callback()

    # Test polling with relative change
    val = None
    attr_proxy.set_polling(True, 0.1, 100, 0.1)
    attr_proxy.subscribe_callback(callback)
    current_value = await attr_proxy.get()
    new_value = current_value * 2
    await attr_proxy.put(new_value)
    polling_period = attr_proxy._polling_period
    await asyncio.sleep(polling_period)
    assert val is not None
    attr_proxy.unsubscribe_callback()

    # Test polling with small changes. This should not update last_reading
    attr_proxy.set_polling(True, 0.1, 100, 1.0)
    attr_proxy.subscribe_callback(callback)
    await asyncio.sleep(0.2)
    current_value = await attr_proxy.get()
    new_value = current_value + 1
    val = None
    await attr_proxy.put(new_value)
    polling_period = attr_proxy._polling_period
    await asyncio.sleep(polling_period * 2)
    assert val is None
    attr_proxy.unsubscribe_callback()

    # Test polling with bad callback
    attr_proxy.subscribe_callback(bad_callback)
    await asyncio.sleep(0.2)
    assert "Could not poll the attribute" in str(attr_proxy.exception)
    attr_proxy.unsubscribe_callback()


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("attr", ["array", "label"])
@pytest.mark.timeout(4.2)
async def test_attribute_poll_stringsandarrays(tango_test_device, attr):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    attr_proxy.support_events = False

    def callback(reading):
        nonlocal val
        val = reading["value"]

    val = None
    attr_proxy.set_polling(True, 0.1)
    attr_proxy.subscribe_callback(callback)
    await asyncio.sleep(0.2)
    assert val is not None
    if isinstance(val, np.ndarray):
        await attr_proxy.put(np.array([[2, 3, 4], [5, 6, 7]]))
        await asyncio.sleep(0.5)
        assert np.all(val == np.array([[2, 3, 4], [5, 6, 7]]))
    if isinstance(val, str):
        await attr_proxy.put("new label")
        await asyncio.sleep(0.5)
        assert val == "new label"

    assert attr_proxy._poll_task
    attr_proxy.unsubscribe_callback()


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_poll_exceptions(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    # Try to poll a non-existent attribute
    attr_proxy = AttributeProxy(device_proxy, "nonexistent")
    attr_proxy.support_events = False
    attr_proxy.set_polling(True, 0.1)

    def callback(reading, value):
        pass

    attr_proxy.subscribe_callback(callback)
    await asyncio.sleep(0.2)
    assert "Could not poll the attribute" in str(attr_proxy.exception)
    attr_proxy.unsubscribe_callback()


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_proxy_put_wait(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "echo")

    cmd_proxy._last_reading = None
    await cmd_proxy.put("test_message", wait=True)
    assert cmd_proxy._last_reading["value"] == "test_message"

    # Force timeout
    cmd_proxy = CommandProxy(device_proxy, "slow_command")
    cmd_proxy._last_reading = None
    with pytest.raises(TimeoutError) as exc_info:
        await cmd_proxy.put(None, wait=True, timeout=0.1)
    assert "command failed" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(3.2)
async def test_command_proxy_put_nowait(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "slow_command")

    # Try to set wait=False
    with pytest.raises(RuntimeError) as exc_info:
        await cmd_proxy.put(None, wait=False)
    assert "is not supported" in str(exc_info.value)

    # Reply before timeout
    cmd_proxy._last_reading = None
    status = cmd_proxy.put(None, timeout=0.5)
    assert cmd_proxy._last_reading is None
    await status
    assert cmd_proxy._last_reading["value"] == "Completed slow command"

    # Timeout
    cmd_proxy._last_reading = None
    status = cmd_proxy.put(None, timeout=0.1)
    with pytest.raises(TimeoutError) as exc_info:
        await status
    assert "Timeout" in str(exc_info.value)

    # No timeout
    cmd_proxy._last_reading = None
    status = cmd_proxy.put(None)
    assert cmd_proxy._last_reading is None
    await status
    assert cmd_proxy._last_reading["value"] == "Completed slow command"


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [True, False])
async def test_command_proxy_put_exceptions(tango_test_device, wait):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "raise_exception_cmd")
    await cmd_proxy.connect()
    with pytest.raises(RuntimeError) as exc_info:
        await cmd_proxy.put(None, wait=True)
    assert "device failure" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_get(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "echo")
    await cmd_proxy.connect()
    await cmd_proxy.put("test_message", wait=True, timeout=1.0)
    value = await cmd_proxy.get()
    assert value == "test_message"


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_get_config(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "clear")
    config = await cmd_proxy.get_config()
    assert config.out_type is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_get_reading(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "echo")
    await cmd_proxy.connect()
    await cmd_proxy.put("test_message", wait=True, timeout=1.0)
    reading = await cmd_proxy.get_reading()
    assert reading["value"] == "test_message"


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_set_polling(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "clear")
    cmd_proxy.set_polling(True, 0.1)
    # Set polling in the command proxy currently does nothing
    assert True


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_init(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "justvalue")
    transport = await make_backend(float, source, connect=False)
    assert transport is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_source(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "justvalue")
    transport = await make_backend(int, source)
    transport_source = transport.source("", True)
    assert transport_source == source


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_datatype_allowed(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    backend = await make_backend(float, source)

    assert backend.datatype_allowed(int)
    assert backend.datatype_allowed(float)
    assert backend.datatype_allowed(str)
    assert backend.datatype_allowed(bool)
    assert backend.datatype_allowed(np.ndarray)
    assert backend.datatype_allowed(StrictEnum)
    assert not backend.datatype_allowed(list)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_connect(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    backend = await make_backend(float, source, connect=False)
    assert backend is not None
    await backend.connect(1)
    backend.read_trl = ""
    with pytest.raises(RuntimeError) as exc_info:
        await backend.connect(1)
    assert "trl not set" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_connect_and_store_config(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    transport = await make_backend(float, source, connect=False)
    await transport._connect_and_store_config(source, 1)
    assert transport.trl_configs[source] is not None

    with pytest.raises(RuntimeError) as exc_info:
        await transport._connect_and_store_config("", 1)
    assert "trl not set" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_put(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnectedError) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect(1)
    source = transport.source("", True)
    await transport.put(2.0)
    val = await transport.proxies[source].get_w_value()
    assert val == 2.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_datakey(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "limitedvalue")

    transport = TangoSignalBackend(float, trl, trl, device_proxy)

    with pytest.raises(NotConnectedError) as exc_info:
        await transport.get_datakey(transport.read_trl)
    assert "Not connected" in str(exc_info.value)

    await transport.connect(1)
    datakey = await transport.get_datakey(trl)
    for key in ["source", "dtype", "shape", "limits", "precision", "units"]:
        assert key in datakey
    assert datakey["source"] == trl
    assert datakey["dtype"] == "number"
    assert datakey["shape"] == []
    for key in ["alarm", "control", "rds", "warning"]:
        assert key in datakey["limits"]
    limits = datakey["limits"]
    assert limits["alarm"] == {"high": 5.0, "low": 1.0}
    assert limits["control"] == {"high": 6.0, "low": 0.0}
    assert limits["rds"] == {"time_difference": 1.0, "value_difference": 1.0}
    assert limits["warning"] == {"high": 4.0, "low": 2.0}


# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tango_transport_get_datakey_enum(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "test_enum")

    class TestEnumType(StrictEnum):
        A = "A"
        B = "B"

    transport = TangoSignalBackend(TestEnumType, trl, trl, device_proxy)
    await transport.connect(1)
    datakey = await transport.get_datakey(trl)
    assert "choices" in datakey
    assert datakey["choices"] == ["A", "B"]


# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tango_transport_get_reading(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnectedError) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect(1)
    reading = await transport.get_reading()
    assert reading["value"] == 2.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_value(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnectedError) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect(1)
    value = await transport.get_value()
    assert value == 2.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_setpoint(tango_test_device):
    source = get_full_attr_trl(tango_test_device, "floatvalue")
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnectedError) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect(1)
    new_setpoint = 2.0
    await transport.put(new_setpoint)
    setpoint = await transport.get_setpoint()
    assert setpoint == new_setpoint


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_read_and_write_trl(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    # Must use a FQTRL, at least on windows.
    read_trl = get_full_attr_trl(tango_test_device, "readback")
    write_trl = get_full_attr_trl(tango_test_device, "setpoint")

    # Test with existing proxy
    transport = TangoSignalBackend(float, read_trl, write_trl, device_proxy)
    await transport.connect(1)
    reading = await transport.get_reading()
    initial_value = reading["value"]
    new_value = initial_value + 1.0
    await transport.put(new_value)
    updated_value = await transport.get_value()
    assert updated_value == new_value

    # Without pre-existing proxy
    transport = TangoSignalBackend(float, read_trl, write_trl, None)
    await transport.connect(1)
    reading = await transport.get_reading()
    initial_value = reading["value"]
    new_value = initial_value + 1.0
    await transport.put(new_value)
    updated_value = await transport.get_value()
    assert updated_value == new_value


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_read_only_trl(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    read_trl = get_full_attr_trl(tango_test_device, "readonly")

    # Test with existing proxy
    transport = TangoSignalBackend(int, read_trl, read_trl, device_proxy)
    await transport.connect(1)
    with pytest.raises(RuntimeError) as exc_info:
        await transport.put(1)
    assert "is not writable" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(14)
async def test_tango_transport_nonexistent_trl(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    nonexistent_trl = get_full_attr_trl(tango_test_device, "nonexistent")

    # Test with existing proxy
    transport = TangoSignalBackend(int, nonexistent_trl, nonexistent_trl, device_proxy)
    with pytest.raises(RuntimeError) as exc_info:
        await transport.connect(1)
    assert "cannot be found" in str(exc_info.value)

    # Without pre-existing proxy
    transport = TangoSignalBackend(int, nonexistent_trl, nonexistent_trl, None)
    with pytest.raises(RuntimeError) as exc_info:
        await transport.connect(1)
    assert "cannot be found" in str(exc_info.value)


# ----------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_type_mismatch_justvalue(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "justvalue")

    transport = TangoSignalBackend(float, trl, trl, device_proxy)
    with pytest.raises(TypeError) as exc_info:
        await transport.connect(1)
    val = str(exc_info.value)
    assert "has type" in val
    assert "int" in val
    assert "float" in val


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_type_mismatch_array(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "array")

    transport = TangoSignalBackend(npt.NDArray[int], trl, trl, device_proxy)
    with pytest.raises(TypeError) as exc_info:
        await transport.connect(1)
    val = str(exc_info.value)
    assert "has type numpy.ndarray" in val
    assert "numpy.dtype" in val
    assert "float" in val
    assert "int" in val


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_type_mismatch_sequence(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "sequence")

    transport = TangoSignalBackend(Sequence[int], trl, trl, device_proxy)
    with pytest.raises(TypeError) as exc_info:
        await transport.connect(1)
    val = str(exc_info.value)
    assert "has type" in val
    assert "str" in val
    assert "Sequence" in val
    assert "int" in val


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_type_mismatch_longstringarray(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = get_full_attr_trl(tango_test_device, "get_longstringarray")

    transport = TangoSignalBackend(TangoDoubleStringTable, trl, trl, device_proxy)
    with pytest.raises(TypeError) as exc_info:
        await transport.connect(1)
    val = str(exc_info.value)
    assert "has type" in val
    assert "TangoLongStringTable" in val
    assert "TangoDoubleStringTable" in val
