import asyncio
import textwrap
import time
from enum import Enum, IntEnum
from random import choice
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from bluesky.protocols import Reading
from test_base_device import TestDevice

from ophyd_async.core import SignalBackend, SignalR, SignalRW, SignalW, SignalX, T
from ophyd_async.tango import (
    TangoSignalBackend,
    __tango_signal_auto,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_w,
    tango_signal_x,
)
from tango import AttrDataFormat, AttrWriteType, DevState
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import set_global_executor
from tango.server import Device, attribute, command
from tango.test_context import MultiDeviceTestContext
from tango.test_utils import assert_close

# --------------------------------------------------------------------
"""
Since TangoTest does not support EchoMode, we create our own Device.

"""


class TestEnum(IntEnum):
    __test__ = False
    A = 0
    B = 1


BASE_TYPES_SET = (
    # type_name, tango_name,    py_type,    sample_values
    ("boolean", "DevBoolean", bool, (True, False)),
    ("short", "DevShort", int, (1, 2, 3, 4, 5)),
    ("ushort", "DevUShort", int, (1, 2, 3, 4, 5)),
    ("long", "DevLong", int, (1, 2, 3, 4, 5)),
    ("ulong", "DevULong", int, (1, 2, 3, 4, 5)),
    ("long64", "DevLong64", int, (1, 2, 3, 4, 5)),
    ("char", "DevUChar", int, (1, 2, 3, 4, 5)),
    ("float", "DevFloat", float, (1.1, 2.2, 3.3, 4.4, 5.5)),
    ("double", "DevDouble", float, (1.1, 2.2, 3.3, 4.4, 5.5)),
    ("string", "DevString", str, ("aaa", "bbb", "ccc")),
    ("state", "DevState", DevState, (DevState.ON, DevState.MOVING, DevState.ALARM)),
    ("enum", "DevEnum", TestEnum, (TestEnum.A, TestEnum.B)),
)

ATTRIBUTES_SET = []
COMMANDS_SET = []

for type_name, tango_type_name, py_type, values in BASE_TYPES_SET:
    ATTRIBUTES_SET.extend(
        [
            (
                f"{type_name}_scalar_attr",
                tango_type_name,
                AttrDataFormat.SCALAR,
                py_type,
                choice(values),
                choice(values),
            ),
            (
                f"{type_name}_spectrum_attr",
                tango_type_name,
                AttrDataFormat.SPECTRUM,
                npt.NDArray[py_type],
                [choice(values), choice(values), choice(values)],
                [choice(values), choice(values), choice(values)],
            ),
            (
                f"{type_name}_image_attr",
                tango_type_name,
                AttrDataFormat.IMAGE,
                npt.NDArray[py_type],
                [
                    [choice(values), choice(values), choice(values)],
                    [choice(values), choice(values), choice(values)],
                ],
                [
                    [choice(values), choice(values), choice(values)],
                    [choice(values), choice(values), choice(values)],
                ],
            ),
        ]
    )

    if tango_type_name == "DevUChar":
        continue
    else:
        COMMANDS_SET.append(
            (
                f"{type_name}_scalar_cmd",
                tango_type_name,
                AttrDataFormat.SCALAR,
                py_type,
                choice(values),
                choice(values),
            )
        )
        if tango_type_name in ["DevState", "DevEnum"]:
            continue
        else:
            COMMANDS_SET.append(
                (
                    f"{type_name}_spectrum_cmd",
                    tango_type_name,
                    AttrDataFormat.SPECTRUM,
                    npt.NDArray[py_type],
                    [choice(values), choice(values), choice(values)],
                    [choice(values), choice(values), choice(values)],
                )
            )


# --------------------------------------------------------------------
#               TestDevice
# --------------------------------------------------------------------
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device():
    with MultiDeviceTestContext(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}], process=True
    ) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
#               Echo device
# --------------------------------------------------------------------
class EchoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        for name, typ, form, _, _, _ in ATTRIBUTES_SET:
            attr = attribute(
                name=name,
                dtype=typ,
                dformat=form,
                access=AttrWriteType.READ_WRITE,
                fget=self.read,
                fset=self.write,
                max_dim_x=3,
                max_dim_y=2,
                enum_labels=[member.name for member in TestEnum],
            )
            self.add_attribute(attr)
            self.set_change_event(name, True, False)

        for name, typ, form, _, _, _ in COMMANDS_SET:
            cmd = command(
                f=getattr(self, name),
                dtype_in=typ,
                dformat_in=form,
                dtype_out=typ,
                dformat_out=form,
            )
            self.add_command(cmd)

    def read(self, attr):
        attr.set_value(self.attr_values[attr.get_name()])

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)

    echo_command_code = textwrap.dedent(
        """\
            def echo_command(self, arg):
                return arg
            """
    )

    for name, _, _, _, _, _ in COMMANDS_SET:
        exec(echo_command_code.replace("echo_command", name))


# --------------------------------------------------------------------
def assert_enum(initial_value, readout_value):
    if type(readout_value) in [list, tuple]:
        for _initial_value, _readout_value in zip(
            initial_value, readout_value, strict=False
        ):
            assert_enum(_initial_value, _readout_value)
    else:
        assert initial_value == readout_value


# --------------------------------------------------------------------
#               fixtures to run Echo device
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
#               helpers to run tests
# --------------------------------------------------------------------
def get_test_descriptor(python_type: type[T], value: T, is_cmd: bool) -> dict:
    if python_type in [bool, int]:
        return {"dtype": "integer", "shape": []}
    if python_type in [float]:
        return {"dtype": "number", "shape": []}
    if python_type in [str]:
        return {"dtype": "string", "shape": []}
    if issubclass(python_type, DevState):
        return {"dtype": "string", "shape": []}
    if issubclass(python_type, Enum):
        return {
            "dtype": "string",
            "shape": [],
        }

    return {
        "dtype": "array",
        "shape": [np.iinfo(np.int32).max] if is_cmd else list(np.array(value).shape),
    }


# --------------------------------------------------------------------
async def make_backend(
    typ: type | None,
    pv: str,
    connect: bool = True,
    allow_events: bool | None = True,
) -> TangoSignalBackend:
    backend = TangoSignalBackend(typ, pv, pv)
    backend.allow_events(allow_events)
    if connect:
        await asyncio.wait_for(backend.connect(), 10)
    return backend


# --------------------------------------------------------------------
async def prepare_device(echo_device: str, pv: str, put_value: T) -> None:
    proxy = await DeviceProxy(echo_device)
    setattr(proxy, pv, put_value)


# --------------------------------------------------------------------
class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.updates: asyncio.Queue[tuple[Reading, Any]] = asyncio.Queue()
        self.backend = backend
        self.subscription = backend.set_callback(self.add_reading_value)

    def add_reading_value(self, reading: Reading, value):
        self.updates.put_nowait((reading, value))

    async def assert_updates(self, expected_value):
        expected_reading = {
            "timestamp": pytest.approx(time.time(), rel=0.1),
            "alarm_severity": 0,
        }
        update_reading, update_value = await self.updates.get()
        get_reading = await self.backend.get_reading()
        # If update_value is a numpy.ndarray, convert it to a list
        if isinstance(update_value, np.ndarray):
            update_value = update_value.tolist()
        assert_close(update_value, expected_value)
        assert_close(await self.backend.get_value(), expected_value)

        update_reading = dict(update_reading)
        update_value = update_reading.pop("value")

        get_reading = dict(get_reading)
        get_value = get_reading.pop("value")

        assert update_reading == expected_reading == get_reading
        assert_close(update_value, expected_value)
        assert_close(get_value, expected_value)

    def close(self):
        self.backend.set_callback(None)


# --------------------------------------------------------------------
async def assert_monitor_then_put(
    echo_device: str,
    pv: str,
    initial_value: T,
    put_value: T,
    descriptor: dict,
    datatype: type[T] | None = None,
):
    await prepare_device(echo_device, pv, initial_value)
    source = echo_device + "/" + pv
    backend = await make_backend(datatype, source, allow_events=True)
    # Make a monitor queue that will monitor for updates
    q = MonitorQueue(backend)
    try:
        assert dict(source=source, **descriptor) == await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(put_value, wait=True)
        assert_close(put_value, await backend.get_setpoint())
        await q.assert_updates(put_value)
    finally:
        q.close()


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value",
    ATTRIBUTES_SET,
    ids=[x[0] for x in ATTRIBUTES_SET],
)
async def test_backend_get_put_monitor_attr(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
):
    try:
        # Set a timeout for the operation to prevent it from running indefinitely
        await asyncio.wait_for(
            assert_monitor_then_put(
                echo_device,
                pv,
                initial_value,
                put_value,
                get_test_descriptor(py_type, initial_value, False),
                py_type,
            ),
            timeout=10,  # Timeout in seconds
        )
    except asyncio.TimeoutError:
        pytest.fail("Test timed out")
    except Exception as e:
        pytest.fail(f"Test failed with exception: {e}")


# --------------------------------------------------------------------
async def assert_put_read(
    echo_device: str,
    pv: str,
    put_value: T,
    descriptor: dict,
    datatype: type[T] | None = None,
):
    source = echo_device + "/" + pv
    backend = await make_backend(datatype, source)
    # Make a monitor queue that will monitor for updates
    assert dict(source=source, **descriptor) == await backend.get_datakey("")
    # Put to new value and check that
    await backend.put(put_value, wait=True)

    expected_reading = {
        "timestamp": pytest.approx(time.time(), rel=0.1),
        "alarm_severity": 0,
    }

    assert_close(await backend.get_value(), put_value)

    get_reading = dict(await backend.get_reading())
    get_reading.pop("value")
    assert expected_reading == get_reading


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value",
    COMMANDS_SET,
    ids=[x[0] for x in COMMANDS_SET],
)
async def test_backend_get_put_monitor_cmd(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
):
    # With the given datatype, check we have the correct initial value and putting works
    descriptor = get_test_descriptor(py_type, initial_value, True)
    await assert_put_read(echo_device, pv, put_value, descriptor, py_type)
    # # With guessed datatype, check we can set it back to the initial value
    await assert_put_read(echo_device, pv, put_value, descriptor)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*tasks)
    del echo_device


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value, use_proxy",
    [
        (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
            use_proxy,
        )
        for (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
        ) in ATTRIBUTES_SET
        for use_proxy in [True, False]
    ],
    ids=[f"{x[0]}_{use_proxy}" for x in ATTRIBUTES_SET for use_proxy in [True, False]],
)
async def test_tango_signal_r(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
    use_proxy: bool,
):
    await prepare_device(echo_device, pv, initial_value)
    source = echo_device + "/" + pv
    proxy = await DeviceProxy(echo_device) if use_proxy else None

    timeout = 0.2
    signal = tango_signal_r(
        datatype=py_type,
        read_trl=source,
        device_proxy=proxy,
        timeout=timeout,
        name="test_signal",
    )
    await signal.connect()
    reading = await signal.read()
    assert_close(reading["test_signal"]["value"], initial_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value, use_proxy",
    [
        (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
            use_proxy,
        )
        for (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
        ) in ATTRIBUTES_SET
        for use_proxy in [True, False]
    ],
    ids=[f"{x[0]}_{use_proxy}" for x in ATTRIBUTES_SET for use_proxy in [True, False]],
)
async def test_tango_signal_w(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
    use_proxy: bool,
):
    await prepare_device(echo_device, pv, initial_value)
    source = echo_device + "/" + pv
    proxy = await DeviceProxy(echo_device) if use_proxy else None

    timeout = 0.2
    signal = tango_signal_w(
        datatype=py_type,
        write_trl=source,
        device_proxy=proxy,
        timeout=timeout,
        name="test_signal",
    )
    await signal.connect()
    status = signal.set(put_value, wait=True, timeout=timeout)
    await status
    assert status.done is True and status.success is True

    status = signal.set(put_value, wait=False, timeout=timeout)
    await status
    assert status.done is True and status.success is True

    status = signal.set(put_value, wait=True)
    await status
    assert status.done is True and status.success is True

    status = signal.set(put_value, wait=False)
    await status
    assert status.done is True and status.success is True


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value, use_proxy",
    [
        (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
            use_proxy,
        )
        for (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
        ) in ATTRIBUTES_SET
        for use_proxy in [True, False]
    ],
    ids=[f"{x[0]}_{use_proxy}" for x in ATTRIBUTES_SET for use_proxy in [True, False]],
)
async def test_tango_signal_rw(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
    use_proxy: bool,
):
    await prepare_device(echo_device, pv, initial_value)
    source = echo_device + "/" + pv
    proxy = await DeviceProxy(echo_device) if use_proxy else None

    timeout = 0.2
    signal = tango_signal_rw(
        datatype=py_type,
        read_trl=source,
        write_trl=source,
        device_proxy=proxy,
        timeout=timeout,
        name="test_signal",
    )
    await signal.connect()
    reading = await signal.read()
    assert_close(reading["test_signal"]["value"], initial_value)
    await signal.set(put_value)
    location = await signal.locate()
    assert_close(location["setpoint"], put_value)
    assert_close(location["readback"], put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("use_proxy", [True, False])
async def test_tango_signal_x(tango_test_device: str, use_proxy: bool):
    proxy = await DeviceProxy(tango_test_device) if use_proxy else None
    timeout = 0.2
    signal = tango_signal_x(
        write_trl=tango_test_device + "/" + "clear",
        device_proxy=proxy,
        timeout=timeout,
        name="test_signal",
    )
    await signal.connect()
    status = signal.trigger()
    await status
    assert status.done is True and status.success is True


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value, use_proxy",
    [
        (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
            use_proxy,
        )
        for (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
        ) in ATTRIBUTES_SET
        for use_proxy in [True, False]
    ],
    ids=[f"{x[0]}_{use_proxy}" for x in ATTRIBUTES_SET for use_proxy in [True, False]],
)
async def test_tango_signal_auto_attrs(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
    use_proxy: bool,
):
    await prepare_device(echo_device, pv, initial_value)
    source = echo_device + "/" + pv
    proxy = await DeviceProxy(echo_device) if use_proxy else None
    timeout = 0.2

    async def _test_signal(dtype, proxy):
        signal = await __tango_signal_auto(
            datatype=dtype,
            trl=source,
            device_proxy=proxy,
            timeout=timeout,
            name="test_signal",
        )
        assert type(signal) is SignalRW
        await signal.connect()
        reading = await signal.read()
        value = reading["test_signal"]["value"]
        if isinstance(value, np.ndarray):
            value = value.tolist()
        assert_close(value, initial_value)

        await signal.set(put_value, wait=True, timeout=timeout)
        reading = await signal.read()
        value = reading["test_signal"]["value"]
        if isinstance(value, np.ndarray):
            value = value.tolist()
        assert_close(value, put_value)

    dtype = py_type
    await _test_signal(dtype, proxy)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pv, tango_type, d_format, py_type, initial_value, put_value, use_dtype, use_proxy",
    [
        (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
            use_dtype,
            use_proxy,
        )
        for (
            pv,
            tango_type,
            d_format,
            py_type,
            initial_value,
            put_value,
        ) in COMMANDS_SET
        for use_dtype in [True, False]
        for use_proxy in [True, False]
    ],
    ids=[
        f"{x[0]}_{use_dtype}_{use_proxy}"
        for x in COMMANDS_SET
        for use_dtype in [True, False]
        for use_proxy in [True, False]
    ],
)
async def test_tango_signal_auto_cmds(
    echo_device: str,
    pv: str,
    tango_type: str,
    d_format: AttrDataFormat,
    py_type: type[T],
    initial_value: T,
    put_value: T,
    use_dtype: bool,
    use_proxy: bool,
):
    source = echo_device + "/" + pv
    timeout = 0.2

    async def _test_signal(dtype, proxy):
        signal = await __tango_signal_auto(
            datatype=dtype,
            trl=source,
            device_proxy=proxy,
            name="test_signal",
            timeout=timeout,
        )
        # Ophyd SignalX does not support types
        assert type(signal) in [SignalR, SignalRW, SignalW]
        await signal.connect()
        assert signal
        reading = await signal.read()
        assert reading["test_signal"]["value"] is None

        await signal.set(put_value, wait=True, timeout=0.1)
        reading = await signal.read()
        value = reading["test_signal"]["value"]
        if isinstance(value, np.ndarray):
            value = value.tolist()
        assert_close(value, put_value)

    proxy = await DeviceProxy(echo_device) if use_proxy else None
    dtype = py_type if use_dtype else None
    await _test_signal(dtype, proxy)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("use_proxy", [True, False])
async def test_tango_signal_auto_cmds_void(tango_test_device: str, use_proxy: bool):
    proxy = await DeviceProxy(tango_test_device) if use_proxy else None
    signal = await __tango_signal_auto(
        datatype=None,
        trl=tango_test_device + "/" + "clear",
        device_proxy=proxy,
    )
    assert type(signal) is SignalX
    await signal.connect()
    assert signal
    await signal.trigger(wait=True)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_auto_badtrl(tango_test_device: str):
    proxy = await DeviceProxy(tango_test_device)
    with pytest.raises(RuntimeError) as exc_info:
        await __tango_signal_auto(
            datatype=None,
            trl=tango_test_device + "/" + "badtrl",
            device_proxy=proxy,
        )
    assert f"Cannot find badtrl in {tango_test_device}" in str(exc_info.value)
