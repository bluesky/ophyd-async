import asyncio
import textwrap
import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from random import choice
from typing import Generic, TypeVar

import numpy as np
import numpy.typing as npt
import pytest
from test_base_device import TestDevice

from ophyd_async.core import SignalBackend, SignalR, SignalRW, SignalW, SignalX
from ophyd_async.tango.core import (
    TangoSignalBackend,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_w,
    tango_signal_x,
)
from ophyd_async.testing import MonitorQueue
from tango import AttrDataFormat, AttrWriteType, DevState
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import set_global_executor
from tango.server import Device, attribute, command
from tango.test_context import MultiDeviceTestContext
from tango.test_utils import assert_close

T = TypeVar("T")


def __tango_signal_auto(*args, **kwargs):
    raise RuntimeError("Fix this later")


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
    # ("string", "DevString", str, ("aaa", "bbb", "ccc")),
    # ("state", "DevState", DevState, (DevState.ON, DevState.MOVING, DevState.ALARM)),
    # ("enum", "DevEnum", TestEnum, (TestEnum.A, TestEnum.B)),
)


@dataclass
class AttributeData(Generic[T]):
    pv: str
    tango_type: str
    d_format: AttrDataFormat
    py_type: type[T]
    initial_value: T
    put_value: T


ATTRIBUTES_SET: list[AttributeData] = []
COMMANDS_SET: list[AttributeData] = []

for type_name, tango_type_name, py_type, values in BASE_TYPES_SET:
    # pytango test utils currently fail to handle bool pytest.approx
    if type_name == "boolean":
        continue
    ATTRIBUTES_SET.extend(
        [
            AttributeData(
                f"{type_name}_scalar_attr",
                tango_type_name,
                AttrDataFormat.SCALAR,
                py_type,
                choice(values),
                choice(values),
            ),
            AttributeData(
                f"{type_name}_spectrum_attr",
                tango_type_name,
                AttrDataFormat.SPECTRUM,
                npt.NDArray[py_type],
                np.array(
                    [choice(values), choice(values), choice(values)], dtype=py_type
                ),
                np.array(
                    [choice(values), choice(values), choice(values)], dtype=py_type
                ),
            ),
            AttributeData(
                f"{type_name}_image_attr",
                tango_type_name,
                AttrDataFormat.IMAGE,
                npt.NDArray[py_type],
                np.array(
                    [
                        [choice(values), choice(values), choice(values)],
                        [choice(values), choice(values), choice(values)],
                    ],
                    dtype=py_type,
                ),
                np.array(
                    [
                        [choice(values), choice(values), choice(values)],
                        [choice(values), choice(values), choice(values)],
                    ],
                    dtype=py_type,
                ),
            ),
        ]
    )

    if tango_type_name == "DevUChar":
        continue
    else:
        COMMANDS_SET.append(
            AttributeData(
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
                AttributeData(
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
        for attr_data in ATTRIBUTES_SET:
            attr = attribute(
                name=attr_data.pv,
                dtype=attr_data.tango_type,
                dformat=attr_data.d_format,
                access=AttrWriteType.READ_WRITE,
                fget=self.read,
                fset=self.write,
                max_dim_x=3,
                max_dim_y=2,
                enum_labels=[member.name for member in TestEnum],
            )
            self.add_attribute(attr)
            self.set_change_event(attr_data.pv, True, False)

        for cmd_data in COMMANDS_SET:
            cmd = command(
                f=getattr(self, cmd_data.pv),
                dtype_in=cmd_data.tango_type,
                dformat_in=cmd_data.d_format,
                dtype_out=cmd_data.tango_type,
                dformat_out=cmd_data.d_format,
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

    for cmd_data in COMMANDS_SET:
        exec(echo_command_code.replace("echo_command", cmd_data.pv))


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
    """Wrapper for making the tango signal backend."""

    backend = TangoSignalBackend(typ, pv, pv)
    backend.allow_events(allow_events)
    if connect:
        await backend.connect(1)
    return backend


# --------------------------------------------------------------------
async def prepare_device(echo_device: str, pv: str, put_value: T) -> None:
    proxy = await DeviceProxy(echo_device)
    setattr(proxy, pv, put_value)


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
    signal = tango_signal_rw(datatype, source)
    backend = signal._connector.backend
    await signal.connect()
    # Make a monitor queue that will monitor for updates
    with MonitorQueue(signal) as q:
        assert dict(source=source, **descriptor) == await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(put_value, wait=True)
        assert_close(put_value, await backend.get_setpoint())
        await q.assert_updates(put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backend_get_put_monitor_attr(echo_device: str):
    try:
        for attr_data in ATTRIBUTES_SET:
            # Set a timeout for the operation to prevent it from running indefinitely
            await asyncio.wait_for(
                assert_monitor_then_put(
                    echo_device,
                    attr_data.pv,
                    attr_data.initial_value,
                    attr_data.put_value,
                    get_test_descriptor(
                        attr_data.py_type, attr_data.initial_value, False
                    ),
                    attr_data.py_type,
                ),
                timeout=100,  # Timeout in seconds
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
async def test_backend_get_put_monitor_cmd(
    echo_device: str,
):
    for cmd_data in COMMANDS_SET:
        # With the given datatype, check we have the correct initial value
        # and putting works
        descriptor = get_test_descriptor(cmd_data.py_type, cmd_data.initial_value, True)
        await assert_put_read(
            echo_device, cmd_data.pv, cmd_data.put_value, descriptor, cmd_data.py_type
        )
        # # With guessed datatype, check we can set it back to the initial value
        await assert_put_read(echo_device, cmd_data.pv, cmd_data.put_value, descriptor)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*tasks)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_r(
    echo_device: str,
):
    timeout = 0.2
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        for attr_data in ATTRIBUTES_SET:
            await prepare_device(echo_device, attr_data.pv, attr_data.initial_value)
            source = echo_device + "/" + attr_data.pv
            signal = tango_signal_r(
                datatype=attr_data.py_type,
                read_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()
            reading = await signal.read()
            assert_close(reading["test_signal"]["value"], attr_data.initial_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_w(
    echo_device: str,
):
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        timeout = 0.2
        for attr_data in ATTRIBUTES_SET:
            await prepare_device(echo_device, attr_data.pv, attr_data.initial_value)
            source = echo_device + "/" + attr_data.pv

            signal = tango_signal_w(
                datatype=attr_data.py_type,
                write_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()
            status = signal.set(attr_data.put_value, wait=True, timeout=timeout)
            await status
            assert status.done is True and status.success is True

            status = signal.set(attr_data.put_value, wait=False, timeout=timeout)
            await status
            assert status.done is True and status.success is True

            status = signal.set(attr_data.put_value, wait=True)
            await status
            assert status.done is True and status.success is True

            status = signal.set(attr_data.put_value, wait=False)
            await status
            assert status.done is True and status.success is True


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_rw(
    echo_device: str,
):
    timeout = 0.2
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        for attr_data in ATTRIBUTES_SET:
            await prepare_device(echo_device, attr_data.pv, attr_data.initial_value)
            source = echo_device + "/" + attr_data.pv

            signal = tango_signal_rw(
                datatype=attr_data.py_type,
                read_trl=source,
                write_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()
            reading = await signal.read()
            assert_close(reading["test_signal"]["value"], attr_data.initial_value)
            await signal.set(attr_data.put_value)
            location = await signal.locate()
            assert_close(location["setpoint"], attr_data.put_value)
            assert_close(location["readback"], attr_data.put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_x(tango_test_device: str):
    timeout = 0.2
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(tango_test_device) if use_proxy else None
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
@pytest.mark.skip("Not sure if we need tango_signal_auto")
async def test_tango_signal_auto_attrs(
    echo_device: str,
):
    timeout = 0.2
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        for attr_data in ATTRIBUTES_SET:
            await prepare_device(echo_device, attr_data.pv, attr_data.initial_value)
            source = echo_device + "/" + attr_data.pv

            async def _test_signal(dtype, proxy, source, initial_value, put_value):
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

            await _test_signal(
                attr_data.dtype,
                proxy,
                source,
                attr_data.initial_value,
                attr_data.put_value,
            )


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.skip("Not sure if we need tango_signal_auto")
@pytest.mark.parametrize(
    "use_dtype, use_proxy",
    [
        (use_dtype, use_proxy)
        for use_dtype in [True, False]
        for use_proxy in [True, False]
    ],
)
async def test_tango_signal_auto_cmds(
    echo_device: str,
    use_dtype: bool,
    use_proxy: bool,
):
    timeout = 0.2
    proxy = await DeviceProxy(echo_device) if use_proxy else None

    for cmd_data in COMMANDS_SET:
        source = echo_device + "/" + cmd_data.pv

        async def _test_signal(dtype, proxy, source, put_value):
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

        dtype = cmd_data.py_type if use_dtype else None
        await _test_signal(dtype, proxy, source, cmd_data.put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.skip("Not sure if we need tango_signal_auto")
async def test_tango_signal_auto_cmds_void(tango_test_device: str, use_proxy: bool):
    for use_proxy in [True, False]:
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
@pytest.mark.skip("Not sure if we need tango_signal_auto")
async def test_tango_signal_auto_badtrl(tango_test_device: str):
    proxy = await DeviceProxy(tango_test_device)
    with pytest.raises(RuntimeError) as exc_info:
        await __tango_signal_auto(
            datatype=None,
            trl=tango_test_device + "/" + "badtrl",
            device_proxy=proxy,
        )
    assert f"Cannot find badtrl in {tango_test_device}" in str(exc_info.value)
