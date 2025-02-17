import asyncio
import time
from enum import Enum
from typing import TypeVar

import numpy as np
import pytest
from test_base_device import TestDevice

from ophyd_async.core import SignalRW
from ophyd_async.tango.core import (
    DevStateEnum,
    TangoDevice,
    TangoSignalBackend,
    get_full_attr_trl,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_w,
    tango_signal_x,
)
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
    everything_signal_info,
)
from ophyd_async.testing import MonitorQueue, assert_reading, assert_value

T = TypeVar("T")


# --------------------------------------------------------------------
#               TestDevice
# --------------------------------------------------------------------
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device(subprocess_helper):
    with subprocess_helper(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}]
    ) as context:
        yield context.trls["test/device/1"]


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
def everything_device_trl(subprocess_helper):
    with subprocess_helper(
        [{"class": OneOfEverythingTangoDevice, "devices": [{"name": "test/device/2"}]}]
    ) as context:
        yield context.trls["test/device/2"]


@pytest.fixture()
async def everything_device(everything_device_trl):
    return TangoDevice(everything_device_trl)


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
    if issubclass(python_type, Enum):
        return {"dtype": "string", "shape": []}
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
async def assert_monitor_then_put(
    signal: SignalRW,
    source: str,
    initial_value: T,
    put_value: T,
    descriptor: dict,
):
    backend = signal._connector.backend
    converter = signal._connector.backend.converter  # type: ignore
    converted_put = converter.value(put_value)
    # Make a monitor queue that will monitor for updates
    with MonitorQueue(signal) as q:
        assert dict(source=source, **descriptor) == await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(converted_put)
        await q.assert_updates(converted_put)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backend_get_put_monitor_attr(everything_device: TangoDevice):
    await everything_device.connect()
    try:
        for attr_data in everything_signal_info:
            signal = getattr(everything_device, attr_data.name)
            source = get_full_attr_trl(everything_device._connector.trl, attr_data.name)
            initial = attr_data.initial_value
            if "my_state" in attr_data.name or "strenum" in attr_data.name:
                # signal_info initial_values use datatype that works on server backend
                initial = signal._connector.backend.converter.value(initial)
            await asyncio.wait_for(
                assert_monitor_then_put(
                    signal,
                    source,
                    initial,
                    attr_data.random_value(),
                    get_test_descriptor(
                        attr_data.py_type, attr_data.initial_value, False
                    ),
                ),
                timeout=10,  # Timeout in seconds
            )
    except asyncio.TimeoutError:
        pytest.fail("Test timed out")
    except Exception as e:
        pytest.fail(f"Test failed with exception: {e}")


# --------------------------------------------------------------------
async def assert_put_read(
    signal: SignalRW,
    source: str,
    put_value: T,
    descriptor: dict,
    datatype: type[T] | None = None,
):
    backend = signal._connector.backend
    # Make a monitor queue that will monitor for updates
    assert dict(source=source, **descriptor) == await backend.get_datakey("")
    # Put to new value and check that
    await backend.put(put_value, wait=True)

    expected_reading = {
        "timestamp": pytest.approx(time.time(), rel=0.1),
        "alarm_severity": 0,
    }

    get_reading = dict(await backend.get_reading())
    get_reading.pop("value")
    assert expected_reading == get_reading


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backend_get_put_monitor_cmd(everything_device: TangoDevice):
    await everything_device.connect()
    for cmd_data in everything_signal_info:
        if cmd_data.cmd_name is None:
            continue
        # With the given datatype, check we have the correct initial value
        # and putting works
        put_value = cmd_data.random_value()
        name = f"{cmd_data.name}_cmd"
        descriptor = get_test_descriptor(cmd_data.py_type, cmd_data.initial_value, True)
        signal = getattr(everything_device, name)
        source = get_full_attr_trl(everything_device._connector.trl, name)
        await assert_put_read(signal, source, put_value, descriptor, cmd_data.py_type)
        # # With guessed datatype, check we can set it back to the initial value
        await assert_put_read(signal, source, put_value, descriptor)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*tasks)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_r(
    everything_device_trl: str,
):
    timeout = 0.2
    for attr_data in everything_signal_info:
        source = get_full_attr_trl(everything_device_trl, attr_data.name)
        signal = tango_signal_r(
            datatype=attr_data.py_type,
            read_trl=source,
            timeout=timeout,
            name="test_signal",
        )
        await signal.connect()
        # value may have changed from initial value if other tests run first
        # casting to array makes tuples returned from tango for arrays work with
        # assert_* functions
        value = np.array(await signal.get_value())
        await assert_value(signal, value)
        await assert_reading(signal, {"test_signal": {"value": value}})


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_w(
    everything_device_trl: str,
):
    timeout = 0.2
    for attr_data in everything_signal_info:
        source = get_full_attr_trl(everything_device_trl, attr_data.name)
        signal = tango_signal_w(
            datatype=attr_data.py_type,
            write_trl=source,
            timeout=timeout,
            name="test_signal",
        )
        await signal.connect()  # have to connect to get correct converter
        converter = signal._connector.backend.converter  # type: ignore

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
    everything_device_trl: str,
):
    timeout = 0.2
    for attr_data in everything_signal_info:
        source = get_full_attr_trl(everything_device_trl, attr_data.name)
        signal = tango_signal_rw(
            datatype=attr_data.py_type,
            read_trl=source,
            write_trl=source,
            timeout=timeout,
            name="test_signal",
        )
        await signal.connect()
        converter = signal._connector.backend.converter  # type: ignore
        put_value = converter.value(attr_data.random_value())
        await signal.set(put_value, wait=True)
        await assert_value(signal, put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_x(tango_test_device: str):
    timeout = 0.2
    signal = tango_signal_x(
        write_trl=get_full_attr_trl(tango_test_device, "clear"),
        timeout=timeout,
        name="test_signal",
    )
    await signal.connect()
    status = signal.trigger()
    await status
    assert status.done is True and status.success is True


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
    "my_state": DevStateEnum.INIT,
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
        [DevStateEnum.INIT.value, DevStateEnum.ON.value, DevStateEnum.MOVING.value],
        dtype=str,
    ),
}

_image_vals = {k: np.vstack((v, v)) for k, v in _array_vals.items()}


async def assert_val_reading(signal, value, name=""):
    await assert_value(signal, value)
    await assert_reading(signal, {name: {"value": value}})


async def test_set_with_converter(everything_device_trl):
    everything_device = TangoDevice(everything_device_trl)
    await everything_device.connect()
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
    await everything_device.my_state.set(DevStateEnum.EXTRACT)
    await everything_device.my_state_spectrum.set(
        [DevStateEnum.OPEN, DevStateEnum.CLOSE, DevStateEnum.MOVING]
    )
    await everything_device.my_state_image.set(
        np.array(
            [
                [DevStateEnum.OPEN, DevStateEnum.CLOSE, DevStateEnum.MOVING],
                [DevStateEnum.OPEN, DevStateEnum.CLOSE, DevStateEnum.MOVING],
            ],
            dtype=DevStateEnum,
        )
    )


async def test_assert_val_reading_everything_tango(everything_device_trl):
    everything_device = TangoDevice(everything_device_trl)
    await everything_device.connect()
    await everything_device.reset_values.trigger()
    await asyncio.sleep(1)
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
