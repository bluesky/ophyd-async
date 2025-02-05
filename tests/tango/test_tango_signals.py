import asyncio
import time
from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum, IntEnum
from random import choice
from typing import Generic, TypeVar

import numpy as np
import pytest
from test_base_device import TestDevice

from ophyd_async.core import SignalBackend, SignalR, SignalRW, SignalW, SignalX
from ophyd_async.tango.core import (
    TangoReadable,
    TangoSignalBackend,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_w,
    tango_signal_x,
)
from ophyd_async.tango.core._tango_transport import (
    TangoEnumConverter,
    TangoEnumImageConverter,
    TangoEnumSpectrumConverter,
)
from ophyd_async.tango.testing._one_of_everything import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
    attribute_datas,
)
from ophyd_async.testing import MonitorQueue, assert_reading, assert_value
from tango import AttrDataFormat, DevState
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import set_global_executor
from tango.test_context import MultiDeviceTestContext
from tango.test_utils import assert_close

T = TypeVar("T")


def __tango_signal_auto(*args, **kwargs):
    raise RuntimeError("Fix this later")


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
        [{"class": OneOfEverythingTangoDevice, "devices": [{"name": "test/device/1"}]}],
        process=True,
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
    source = echo_device + "/" + pv
    signal = tango_signal_rw(datatype, source)
    backend = signal._connector.backend
    await signal.connect()
    converter = signal._connector.backend.converter  # type: ignore
    converted_initial = converter.value(initial_value)
    await prepare_device(echo_device, pv, converted_initial)
    converted_put = converter.value(put_value)
    # Make a monitor queue that will monitor for updates
    with MonitorQueue(signal) as q:
        assert dict(source=source, **descriptor) == await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(converted_put, wait=True)
        assert_close(converted_put, await backend.get_setpoint())
        await q.assert_updates(put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backend_get_put_monitor_attr(echo_device: str):
    try:
        for attr_data in attribute_datas:
            if "state" in attr_data.name:
                print("skipping for now", attr_data.name)
                continue
            # Set a timeout for the operation to prevent it from running indefinitely
            await asyncio.wait_for(
                assert_monitor_then_put(
                    echo_device,
                    attr_data.name,
                    attr_data.initial_value,
                    attr_data.random_value(),
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
    for cmd_data in attribute_datas:
        if (
            cmd_data.dformat == AttrDataFormat.IMAGE
            or cmd_data.tango_type == "DevUChar"
            or (
                cmd_data.dformat != AttrDataFormat.SCALAR
                and cmd_data.tango_type
                in [
                    "DevState",
                    "DevEnum",
                ]
            )
        ):
            continue
        print(cmd_data.tango_type, cmd_data.dformat)
        # With the given datatype, check we have the correct initial value
        # and putting works
        put_value = cmd_data.random_value()
        name = f"{cmd_data.name}_cmd"
        descriptor = get_test_descriptor(cmd_data.py_type, cmd_data.initial_value, True)
        await assert_put_read(
            echo_device, name, put_value, descriptor, cmd_data.py_type
        )
        # # With guessed datatype, check we can set it back to the initial value
        await assert_put_read(echo_device, name, put_value, descriptor)
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
        for attr_data in attribute_datas:
            if "state" in attr_data.name:
                print("skipping for now", attr_data.name)
                continue
            source = echo_device + "/" + attr_data.name
            signal = tango_signal_r(
                datatype=attr_data.py_type,
                read_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()
            # need to convert int into strings for testing enums
            converter = signal._connector.backend.converter  # type: ignore
            value = converter.value(attr_data.initial_value)
            await assert_value(signal, value)
            await assert_reading(signal, {"test_signal": {"value": value}})


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_w(
    echo_device: str,
):
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        timeout = 0.2
        for attr_data in attribute_datas:
            if "state" in attr_data.name:
                print("skipping for now", attr_data.name)
                continue
            source = echo_device + "/" + attr_data.name
            signal = tango_signal_w(
                datatype=attr_data.py_type,
                write_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()  # have to connect to get correct converter
            converter = signal._connector.backend.converter  # type: ignore
            initial = converter.value(attr_data.initial_value)
            await prepare_device(echo_device, attr_data.name, initial)

            put_value = converter.value(attr_data.random_value())
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
async def test_tango_signal_rw(
    echo_device: str,
):
    timeout = 0.2
    for use_proxy in [True, False]:
        proxy = await DeviceProxy(echo_device) if use_proxy else None
        for attr_data in attribute_datas:
            if "state" in attr_data.name:
                print("skipping for now", attr_data.name)
                continue

            source = echo_device + "/" + attr_data.name
            signal = tango_signal_rw(
                datatype=attr_data.py_type,
                read_trl=source,
                write_trl=source,
                device_proxy=proxy,
                timeout=timeout,
                name="test_signal",
            )
            await signal.connect()
            converter = signal._connector.backend.converter  # type: ignore
            initial = converter.value(attr_data.initial_value)
            put_value = converter.value(attr_data.random_value())
            await prepare_device(echo_device, attr_data.name, initial)
            reading = await signal.read()
            assert_close(reading["test_signal"]["value"], initial)
            await signal.set(put_value)
            location = await signal.locate()
            assert_close(location["setpoint"], put_value)
            assert_close(location["readback"], put_value)


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
        for attr_data in attribute_datas:
            await prepare_device(echo_device, attr_data.name, attr_data.initial_value)
            source = echo_device + "/" + attr_data.name

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
                attr_data.py_type,
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

    for cmd_data in attribute_datas:
        source = echo_device + "/" + cmd_data.name + "_cmd"

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
        await _test_signal(dtype, proxy, source, cmd_data.random_value())


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


@pytest.fixture(scope="module")  # module level scope doesn't work properly...
def everything_device_trl() -> Generator[str]:
    with MultiDeviceTestContext(
        [
            {
                "class": OneOfEverythingTangoDevice,
                "devices": [{"name": "everything/device/1"}],
            }
        ],
        process=True,
    ) as context:
        yield context.get_device_access("everything/device/1")


@pytest.fixture
async def everything_device(everything_device_trl) -> TangoReadable:
    ophyd_device = TangoReadable(everything_device_trl)
    await ophyd_device.connect()  # TODO: this is fine because we are forking
    await ophyd_device.reset_values.trigger()  # type: ignore
    return ophyd_device


_scalar_vals = {
    "str": "test_string",
    "bool": True,
    "strenum": ExampleStrEnum.B,
    "int8": 1,
    "uint8": 1,
    "int16": 1,
    "uint16": 1,
    "int32": 1,
    "uint32": 1,
    "int64": 1,
    "uint64": 1,
    "float32": 1.234,
    "float64": 1.234,
    "my_state": DevState.INIT,
}
_array_vals = {
    "int8": np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
    "uint8": np.array([0, 255, 0, 1, 2, 3, 4], dtype=np.uint8),
    "int16": np.array([-32768, 32767, 0, 1, 2, 3, 4], dtype=np.int16),
    "uint16": np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
    "int32": np.array([-2147483648, 2147483647, 0, 1, 2, 3, 4], dtype=np.int32),
    "uint32": np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
    "int64": np.array(
        [-9223372036854775808, 9223372036854775807, 0, 1, 2, 3, 4],
        dtype=np.int64,
    ),
    "uint64": np.array([0, 18446744073709551615, 0, 1, 2, 3, 4], dtype=np.uint64),
    "float32": np.array(
        [
            -3.4028235e38,
            3.4028235e38,
            1.1754944e-38,
            1.4012985e-45,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=np.float32,
    ),
    "float64": np.array(
        [
            -1.79769313e308,
            1.79769313e308,
            2.22507386e-308,
            4.94065646e-324,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=np.float64,
    ),
    "strenum": np.array(
        [ExampleStrEnum.A.value, ExampleStrEnum.B.value, ExampleStrEnum.C.value],
        dtype=str,
    ),
    "str": ["one", "two", "three"],
    "bool": np.array([False, True]),
    "my_state": np.array(
        [DevState.INIT, DevState.ON, DevState.MOVING]
    ),  # fails if we specify dtype
}

_image_vals = {k: np.vstack((v, v)) for k, v in _array_vals.items()}


async def assert_val_reading(signal, value, name=""):
    await assert_value(signal, value)
    await assert_reading(signal, {name: {"value": value}})


async def test_set_with_converter(everything_device):
    with pytest.raises(TypeError):
        await everything_device.strenum.set(0)
    with pytest.raises(ValueError):
        await everything_device.strenum.set("NON_ENUM_VALUE")
    await everything_device.strenum.set("AAA")
    await everything_device.strenum.set(ExampleStrEnum.B)
    await everything_device.strenum.set(ExampleStrEnum.C.value)

    # setting enum spectrum works with lists and arrays
    await everything_device.strenum_spectrum.set(["AAA", "BBB"])
    await everything_device.strenum_spectrum.set(np.array(["BBB", "CCC"]))
    await everything_device.strenum_spectrum.set(
        [
            ExampleStrEnum.B,
            ExampleStrEnum.C,
        ]
    )
    await everything_device.strenum_spectrum.set(
        np.array(
            [
                ExampleStrEnum.A,
                ExampleStrEnum.B,
            ],
            dtype=ExampleStrEnum,  # doesn't work when dtype is str
        )
    )

    await everything_device.strenum_image.set([["AAA", "BBB"], ["AAA", "BBB"]])
    await everything_device.strenum_image.set(
        np.array([["AAA", "BBB"], ["AAA", "BBB"]])
    )
    await everything_device.strenum_image.set(
        [
            [
                ExampleStrEnum.B,
                ExampleStrEnum.C,
            ],
            [
                ExampleStrEnum.B,
                ExampleStrEnum.C,
            ],
        ]
    )
    await everything_device.strenum_image.set(
        np.array(
            [
                [
                    ExampleStrEnum.B,
                    ExampleStrEnum.C,
                ],
                [
                    ExampleStrEnum.B,
                    ExampleStrEnum.C,
                ],
            ],
            dtype=ExampleStrEnum,
        )
    )


async def test_assert_val_reading_everything_tango(everything_device):
    await assert_val_reading(everything_device.str, _scalar_vals["str"])
    await assert_val_reading(everything_device.bool, _scalar_vals["bool"])
    await assert_val_reading(everything_device.strenum, _scalar_vals["strenum"])
    await assert_val_reading(everything_device.int8, _scalar_vals["int8"])
    await assert_val_reading(everything_device.uint8, _scalar_vals["uint8"])
    await assert_val_reading(everything_device.int16, _scalar_vals["int16"])
    await assert_val_reading(everything_device.uint16, _scalar_vals["uint16"])
    await assert_val_reading(everything_device.int32, _scalar_vals["int32"])
    await assert_val_reading(everything_device.uint32, _scalar_vals["uint32"])
    await assert_val_reading(everything_device.int64, _scalar_vals["int64"])
    await assert_val_reading(everything_device.uint64, _scalar_vals["uint64"])
    await assert_val_reading(everything_device.float32, _scalar_vals["float32"])
    await assert_val_reading(everything_device.float64, _scalar_vals["float64"])
    await assert_val_reading(everything_device.my_state, _scalar_vals["my_state"])

    await assert_val_reading(everything_device.str_spectrum, _array_vals["str"])
    await assert_val_reading(everything_device.bool_spectrum, _array_vals["bool"])
    await assert_val_reading(everything_device.strenum_spectrum, _array_vals["strenum"])
    await assert_val_reading(everything_device.int8_spectrum, _array_vals["int8"])
    await assert_val_reading(everything_device.uint8_spectrum, _array_vals["uint8"])
    await assert_val_reading(everything_device.int16_spectrum, _array_vals["int16"])
    await assert_val_reading(everything_device.uint16_spectrum, _array_vals["uint16"])
    await assert_val_reading(everything_device.int32_spectrum, _array_vals["int32"])
    await assert_val_reading(everything_device.uint32_spectrum, _array_vals["uint32"])
    await assert_val_reading(everything_device.int64_spectrum, _array_vals["int64"])
    await assert_val_reading(everything_device.uint64_spectrum, _array_vals["uint64"])
    await assert_val_reading(everything_device.float32_spectrum, _array_vals["float32"])
    await assert_val_reading(everything_device.float64_spectrum, _array_vals["float64"])
    await assert_val_reading(
        everything_device.my_state_spectrum, _array_vals["my_state"]
    )

    await assert_val_reading(everything_device.str_image, _image_vals["str"])
    await assert_val_reading(everything_device.bool_image, _image_vals["bool"])
    await assert_val_reading(everything_device.strenum_image, _image_vals["strenum"])
    await assert_val_reading(everything_device.int8_image, _image_vals["int8"])
    await assert_val_reading(everything_device.uint8_image, _image_vals["uint8"])
    await assert_val_reading(everything_device.int16_image, _image_vals["int16"])
    await assert_val_reading(everything_device.uint16_image, _image_vals["uint16"])
    await assert_val_reading(everything_device.int32_image, _image_vals["int32"])
    await assert_val_reading(everything_device.uint32_image, _image_vals["uint32"])
    await assert_val_reading(everything_device.int64_image, _image_vals["int64"])
    await assert_val_reading(everything_device.uint64_image, _image_vals["uint64"])
    await assert_val_reading(everything_device.float32_image, _image_vals["float32"])
    await assert_val_reading(everything_device.float64_image, _image_vals["float64"])
    await assert_val_reading(everything_device.my_state_image, _image_vals["my_state"])
