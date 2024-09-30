import asyncio
from enum import Enum

import numpy as np
import numpy.typing as npt
import pytest
from test_base_device import TestDevice
from test_tango_signals import (
    EchoDevice,
    make_backend,
    prepare_device,
)

from ophyd_async.core import (
    NotConnected,
)
from ophyd_async.tango import (
    AttributeProxy,
    CommandProxy,
    TangoSignalBackend,
    ensure_proper_executor,
    get_dtype_extended,
    get_python_type,
    get_tango_trl,
    get_trl_descriptor,
)
from tango import (
    CmdArgType,
    DevState,
)
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import (
    AsyncioExecutor,
    get_global_executor,
    set_global_executor,
)
from tango.test_context import MultiDeviceTestContext


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device():
    with MultiDeviceTestContext(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}], process=True
    ) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def echo_device():
    with MultiDeviceTestContext(
        [{"class": EchoDevice, "devices": [{"name": "test/device/1"}]}], process=True
    ) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


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
    "tango_type, expected",
    [
        (CmdArgType.DevVoid, (False, None, "string")),
        (CmdArgType.DevBoolean, (False, bool, "integer")),
        (CmdArgType.DevShort, (False, int, "integer")),
        (CmdArgType.DevLong, (False, int, "integer")),
        (CmdArgType.DevFloat, (False, float, "number")),
        (CmdArgType.DevDouble, (False, float, "number")),
        (CmdArgType.DevUShort, (False, int, "integer")),
        (CmdArgType.DevULong, (False, int, "integer")),
        (CmdArgType.DevString, (False, str, "string")),
        (CmdArgType.DevVarCharArray, (True, list[str], "string")),
        (CmdArgType.DevVarShortArray, (True, int, "integer")),
        (CmdArgType.DevVarLongArray, (True, int, "integer")),
        (CmdArgType.DevVarFloatArray, (True, float, "number")),
        (CmdArgType.DevVarDoubleArray, (True, float, "number")),
        (CmdArgType.DevVarUShortArray, (True, int, "integer")),
        (CmdArgType.DevVarULongArray, (True, int, "integer")),
        (CmdArgType.DevVarStringArray, (True, str, "string")),
        # (CmdArgType.DevVarLongStringArray, (True, str, "string")),
        # (CmdArgType.DevVarDoubleStringArray, (True, str, "string")),
        (CmdArgType.DevState, (False, CmdArgType.DevState, "string")),
        (CmdArgType.ConstDevString, (False, str, "string")),
        (CmdArgType.DevVarBooleanArray, (True, bool, "integer")),
        (CmdArgType.DevUChar, (False, int, "integer")),
        (CmdArgType.DevLong64, (False, int, "integer")),
        (CmdArgType.DevULong64, (False, int, "integer")),
        (CmdArgType.DevVarLong64Array, (True, int, "integer")),
        (CmdArgType.DevVarULong64Array, (True, int, "integer")),
        (CmdArgType.DevEncoded, (False, list[str], "string")),
        (CmdArgType.DevEnum, (False, Enum, "string")),
        # (CmdArgType.DevPipeBlob, (False, list[str], "string")),
        (float, (False, float, "number")),
    ],
)
def test_get_python_type(tango_type, expected):
    if tango_type is not float:
        assert get_python_type(tango_type) == expected
    else:
        # get_python_type should raise a TypeError
        with pytest.raises(TypeError) as exc_info:
            get_python_type(tango_type)
        assert str(exc_info.value) == "Unknown TangoType"


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
    "datatype, tango_resource, expected_descriptor",
    [
        (
            int,
            "test/device/1/justvalue",
            {"source": "test/device/1/justvalue", "dtype": "integer", "shape": []},
        ),
        (
            float,
            "test/device/1/limitedvalue",
            {"source": "test/device/1/limitedvalue", "dtype": "number", "shape": []},
        ),
        (
            npt.NDArray[float],
            "test/device/1/array",
            {"source": "test/device/1/array", "dtype": "array", "shape": [2, 3]},
        ),
        # Add more test cases as needed
    ],
)
async def test_get_trl_descriptor(
    tango_test_device, datatype, tango_resource, expected_descriptor
):
    proxy = await DeviceProxy(tango_test_device)
    tr_configs = {
        tango_resource.split("/")[-1]: await proxy.get_attribute_config(
            tango_resource.split("/")[-1]
        )
    }
    descriptor = get_trl_descriptor(datatype, tango_resource, tr_configs)
    assert descriptor == expected_descriptor


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trl, proxy_needed, expected_type, should_raise",
    [
        ("test/device/1/justvalue", True, AttributeProxy, False),
        ("test/device/1/justvalue", False, AttributeProxy, False),
        ("test/device/1/clear", True, CommandProxy, False),
        ("test/device/1/clear", False, CommandProxy, False),
        ("test/device/1/nonexistent", True, None, True),
    ],
)
async def test_get_tango_trl(
    tango_test_device, trl, proxy_needed, expected_type, should_raise
):
    proxy = await DeviceProxy(tango_test_device) if proxy_needed else None
    if should_raise:
        with pytest.raises(RuntimeError):
            await get_tango_trl(trl, proxy)
    else:
        result = await get_tango_trl(trl, proxy)
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
    "attr, wait",
    [("justvalue", True), ("justvalue", False), ("array", True), ("array", False)],
)
async def test_attribute_proxy_put(tango_test_device, attr, wait):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)

    old_value = await attr_proxy.get()
    new_value = old_value + 1
    status = await attr_proxy.put(new_value, wait=wait, timeout=0.1)
    if status:
        await status
    else:
        if not wait:
            raise AssertionError("If wait is False, put should return a status object")
    updated_value = await attr_proxy.get()
    if isinstance(new_value, np.ndarray):
        assert np.all(updated_value == new_value)
    else:
        assert updated_value == new_value


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [True, False])
async def test_attribute_proxy_put_force_timeout(tango_test_device, wait):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "slow_attribute")
    with pytest.raises(TimeoutError) as exc_info:
        status = await attr_proxy.put(3.0, wait=wait, timeout=0.1)
        await status
    assert "attr put failed" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [True, False])
async def test_attribute_proxy_put_exceptions(tango_test_device, wait):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "raise_exception_attr")
    with pytest.raises(RuntimeError) as exc_info:
        status = await attr_proxy.put(3.0, wait=wait)
        await status
    assert "device failure" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr, new_value", [("justvalue", 10), ("array", np.array([[2, 3, 4], [5, 6, 7]]))]
)
async def test_attribute_proxy_get_w_value(tango_test_device, attr, new_value):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    await attr_proxy.put(new_value)
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
async def test_attribute_subscribe_callback(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    backend = await make_backend(float, source)
    attr_proxy = backend.proxies[source]
    val = None

    def callback(reading, value):
        nonlocal val
        val = value

    attr_proxy.subscribe_callback(callback)
    assert attr_proxy.has_subscription()
    old_value = await attr_proxy.get()
    new_value = old_value + 1
    await attr_proxy.put(new_value)
    await asyncio.sleep(0.2)
    attr_proxy.unsubscribe_callback()
    assert val == new_value

    attr_proxy.set_polling(False)
    attr_proxy.support_events = False
    with pytest.raises(RuntimeError) as exc_info:
        attr_proxy.subscribe_callback(callback)
    assert "Cannot set a callback" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribute_unsubscribe_callback(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    backend = await make_backend(float, source)
    attr_proxy = backend.proxies[source]

    def callback(reading, value):
        pass

    attr_proxy.subscribe_callback(callback)
    assert attr_proxy.has_subscription()
    attr_proxy.unsubscribe_callback()
    assert not attr_proxy.has_subscription()


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
async def test_attribute_poll(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, "floatvalue")
    attr_proxy.support_events = False

    def callback(reading, value):
        nonlocal val
        val = value

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
async def test_attribute_poll_stringsandarrays(tango_test_device, attr):
    device_proxy = await DeviceProxy(tango_test_device)
    attr_proxy = AttributeProxy(device_proxy, attr)
    attr_proxy.support_events = False

    def callback(reading, value):
        nonlocal val
        val = value

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


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_proxy_put_wait(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "clear")

    cmd_proxy._last_reading = None
    await cmd_proxy.put(None, wait=True)
    assert cmd_proxy._last_reading["value"] == "Received clear command"

    # Force timeout
    cmd_proxy = CommandProxy(device_proxy, "slow_command")
    cmd_proxy._last_reading = None
    with pytest.raises(TimeoutError) as exc_info:
        await cmd_proxy.put(None, wait=True, timeout=0.1)
    assert "command failed" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_proxy_put_nowait(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "slow_command")

    # Reply before timeout
    cmd_proxy._last_reading = None
    status = await cmd_proxy.put(None, wait=False, timeout=0.5)
    assert cmd_proxy._last_reading is None
    await status
    assert cmd_proxy._last_reading["value"] == "Completed slow command"

    # Timeout
    cmd_proxy._last_reading = None
    status = await cmd_proxy.put(None, wait=False, timeout=0.1)
    with pytest.raises(TimeoutError) as exc_info:
        await status
    assert str(exc_info.value) == "Timeout while waiting for command reply"

    # No timeout
    cmd_proxy._last_reading = None
    status = await cmd_proxy.put(None, wait=False)
    assert cmd_proxy._last_reading is None
    await status
    assert cmd_proxy._last_reading["value"] == "Completed slow command"


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [True, False])
async def test_command_proxy_put_exceptions(tango_test_device, wait):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "raise_exception_cmd")
    with pytest.raises(RuntimeError) as exc_info:
        await cmd_proxy.put(None, wait=True)
    assert "device failure" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_command_get(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    cmd_proxy = CommandProxy(device_proxy, "clear")
    await cmd_proxy.put(None, wait=True, timeout=1.0)
    reading = cmd_proxy._last_reading
    assert reading["value"] is not None


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
    cmd_proxy = CommandProxy(device_proxy, "clear")
    await cmd_proxy.put(None, wait=True, timeout=1.0)
    reading = await cmd_proxy.get_reading()
    assert reading["value"] is not None


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
async def test_tango_transport_init(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)
    assert transport is not None


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_source(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source)
    transport_source = transport.source("")
    assert transport_source == source


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_datatype_allowed(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    backend = await make_backend(float, source)

    assert backend.datatype_allowed(int)
    assert backend.datatype_allowed(float)
    assert backend.datatype_allowed(str)
    assert backend.datatype_allowed(bool)
    assert backend.datatype_allowed(np.ndarray)
    assert backend.datatype_allowed(Enum)
    assert backend.datatype_allowed(DevState)
    assert not backend.datatype_allowed(list)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_connect(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    backend = await make_backend(float, source, connect=False)
    assert backend is not None
    await backend.connect()
    backend.read_trl = ""
    with pytest.raises(RuntimeError) as exc_info:
        await backend.connect()
    assert "trl not set" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_connect_and_store_config(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)
    await transport._connect_and_store_config(source)
    assert transport.trl_configs[source] is not None

    with pytest.raises(RuntimeError) as exc_info:
        await transport._connect_and_store_config("")
    assert "trl not set" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_put(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnected) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect()
    source = transport.source("")
    await transport.put(2.0)
    val = await transport.proxies[source].get_w_value()
    assert val == 2.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_datakey(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)
    await transport.connect()
    datakey = await transport.get_datakey(source)
    assert datakey["source"] == source
    assert datakey["dtype"] == "number"
    assert datakey["shape"] == []


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_reading(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnected) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect()
    reading = await transport.get_reading()
    assert reading["value"] == 1.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_value(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnected) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect()
    value = await transport.get_value()
    assert value == 1.0


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_get_setpoint(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnected) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect()
    new_setpoint = 2.0
    await transport.put(new_setpoint)
    setpoint = await transport.get_setpoint()
    assert setpoint == new_setpoint


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_callback(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)

    with pytest.raises(NotConnected) as exc_info:
        await transport.put(1.0)
    assert "Not connected" in str(exc_info.value)

    await transport.connect()
    val = None

    def callback(reading, value):
        nonlocal val
        val = value

    # Correct usage
    transport.set_callback(callback)
    current_value = await transport.get_value()
    new_value = current_value + 2
    await transport.put(new_value)
    await asyncio.sleep(0.1)
    assert val == new_value

    # Try to add second callback
    with pytest.raises(RuntimeError) as exc_info:
        transport.set_callback(callback)
    assert "Cannot set a callback when one is already set"

    transport.set_callback(None)

    # Try to add a callback to a non-callable proxy
    transport.allow_events(False)
    transport.set_polling(False)
    with pytest.raises(RuntimeError) as exc_info:
        transport.set_callback(callback)
    assert "Cannot set event" in str(exc_info.value)

    # Try to add a non-callable callback
    transport.allow_events(True)
    with pytest.raises(RuntimeError) as exc_info:
        transport.set_callback(1)
    assert "Callback must be a callable" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_set_polling(echo_device):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)
    transport.set_polling(True, 0.1, 1, 0.1)
    assert transport._polling == (True, 0.1, 1, 0.1)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("allow", [True, False])
async def test_tango_transport_allow_events(echo_device, allow):
    await prepare_device(echo_device, "float_scalar_attr", 1.0)
    source = echo_device + "/" + "float_scalar_attr"
    transport = await make_backend(float, source, connect=False)
    transport.allow_events(allow)
    assert transport.support_events == allow


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_read_and_write_trl(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = device_proxy.dev_name()
    read_trl = trl + "/" + "readback"
    write_trl = trl + "/" + "setpoint"

    # Test with existing proxy
    transport = TangoSignalBackend(float, read_trl, write_trl, device_proxy)
    await transport.connect()
    reading = await transport.get_reading()
    initial_value = reading["value"]
    new_value = initial_value + 1.0
    await transport.put(new_value)
    updated_value = await transport.get_value()
    assert updated_value == new_value

    # Without pre-existing proxy
    transport = TangoSignalBackend(float, read_trl, write_trl, None)
    await transport.connect()
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
    trl = device_proxy.dev_name()
    read_trl = trl + "/" + "readonly"

    # Test with existing proxy
    transport = TangoSignalBackend(int, read_trl, read_trl, device_proxy)
    await transport.connect()
    with pytest.raises(RuntimeError) as exc_info:
        await transport.put(1)
    assert "is not writable" in str(exc_info.value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_transport_nonexistent_trl(tango_test_device):
    device_proxy = await DeviceProxy(tango_test_device)
    trl = device_proxy.dev_name()
    nonexistent_trl = trl + "/" + "nonexistent"

    # Test with existing proxy
    transport = TangoSignalBackend(int, nonexistent_trl, nonexistent_trl, device_proxy)
    with pytest.raises(RuntimeError) as exc_info:
        await transport.connect()
    assert "cannot be found" in str(exc_info.value)

    # Without pre-existing proxy
    transport = TangoSignalBackend(int, nonexistent_trl, nonexistent_trl, None)
    with pytest.raises(RuntimeError) as exc_info:
        await transport.connect()
    assert "cannot be found" in str(exc_info.value)
