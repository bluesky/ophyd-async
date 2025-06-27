import asyncio
import time
from enum import Enum
from typing import Annotated as A
from typing import TypeVar

import numpy as np
import pytest
from test_base_device import TestDevice

from ophyd_async.core import SignalRW, StandardReadable
from ophyd_async.core import StandardReadableFormat as Format
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
)
from ophyd_async.testing import (
    MonitorQueue,
    assert_reading,
    assert_value,
    partial_reading,
)

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


class TangoEverythingOphydDevice(TangoDevice, StandardReadable):
    # datatype of enum commands must be explicitly hinted
    strenum_cmd: A[SignalRW[ExampleStrEnum], Format.HINTED_UNCACHED_SIGNAL]


@pytest.fixture()
async def everything_device(everything_device_trl):
    return TangoEverythingOphydDevice(everything_device_trl)


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
    # Make a monitor queue that will monitor for updates
    with MonitorQueue(signal) as q:
        assert dict(source=source, **descriptor) == await backend.get_datakey("")
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(put_value)
        await q.assert_updates(put_value)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(18.8)
async def test_backend_get_put_monitor_attr(
    everything_device: TangoDevice, everything_signal_info
):
    await everything_device.connect()
    try:
        for attr_data in everything_signal_info.values():
            signal = getattr(everything_device, attr_data.name)
            source = get_full_attr_trl(everything_device._connector.trl, attr_data.name)
            await asyncio.wait_for(
                assert_monitor_then_put(
                    signal,
                    source,
                    attr_data.initial,
                    attr_data.random_value(),
                    get_test_descriptor(attr_data.py_type, attr_data.initial, False),
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
    datatype: type[T] | None = None,  # TODO reimplement this
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
async def test_backend_get_put_monitor_cmd(
    everything_device: TangoDevice, everything_signal_info
):
    await everything_device.connect()
    for cmd_data in everything_signal_info.values():
        if cmd_data.cmd_name is None:
            continue
        put_value = cmd_data.random_value()
        # With the given datatype, check we have the correct initial value
        # and putting works
        descriptor = get_test_descriptor(cmd_data.py_type, cmd_data.initial, True)
        signal = getattr(everything_device, cmd_data.cmd_name)
        source = get_full_attr_trl(everything_device._connector.trl, cmd_data.cmd_name)
        await assert_put_read(signal, source, put_value, descriptor, cmd_data.py_type)
        # # With guessed datatype, check we can set it back to the initial value
        await assert_put_read(signal, source, put_value, descriptor)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*tasks)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_r(everything_device_trl: str, everything_signal_info):
    timeout = 0.2
    for attr_data in everything_signal_info.values():
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
        await assert_reading(signal, {"test_signal": partial_reading(value)})


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tango_signal_w(everything_device_trl: str, everything_signal_info):
    timeout = 0.2
    for attr_data in everything_signal_info.values():
        source = get_full_attr_trl(everything_device_trl, attr_data.name)
        signal = tango_signal_w(
            datatype=attr_data.py_type,
            write_trl=source,
            timeout=timeout,
            name="test_signal",
        )
        await signal.connect()  # have to connect to get correct converter

        put_value = attr_data.random_value()

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
async def test_tango_signal_rw(everything_device_trl: str, everything_signal_info):
    timeout = 0.2
    for attr_data in everything_signal_info.values():
        source = get_full_attr_trl(everything_device_trl, attr_data.name)
        signal = tango_signal_rw(
            datatype=attr_data.py_type,
            read_trl=source,
            write_trl=source,
            timeout=timeout,
            name="test_signal",
        )
        await signal.connect()
        put_value = attr_data.random_value()
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


async def assert_val_reading(signal, value, name=""):
    await assert_value(signal, value)
    await assert_reading(signal, {name: partial_reading(value)})


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
            ExampleStrEnum.B.value,
            ExampleStrEnum.C.value,
        ]
    )
    await everything_device.strenum_spectrum.set(
        np.array(
            [
                ExampleStrEnum.A,
                ExampleStrEnum.B,
            ],
            dtype=ExampleStrEnum,
            # when using enum instances, must use array with correct dtype
            # passing this as a list will cast the strings incorrectly
        )
    )

    await everything_device.strenum_image.set([["AAA", "BBB"], ["AAA", "BBB"]])
    await everything_device.strenum_image.set(
        np.array([["AAA", "BBB"], ["AAA", "BBB"]])
    )
    await everything_device.strenum_image.set(
        [
            [
                ExampleStrEnum.B.value,
                ExampleStrEnum.C.value,
            ],
            [
                ExampleStrEnum.B.value,
                ExampleStrEnum.C.value,
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
        np.array(
            [
                DevStateEnum.OPEN,
                DevStateEnum.CLOSE,
                DevStateEnum.MOVING,
            ],
            dtype=DevStateEnum,
        )
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


@pytest.mark.timeout(18.8)
async def test_assert_val_reading_everything_tango(
    everything_device_trl, everything_signal_info
):
    esi = everything_signal_info
    everything_device = TangoDevice(everything_device_trl)
    await everything_device.connect()
    await everything_device.reset_values.trigger()
    await asyncio.sleep(1)
    await assert_val_reading(everything_device.str, esi["str"].initial)
    await assert_val_reading(everything_device.bool, esi["bool"].initial)
    await assert_val_reading(everything_device.strenum, esi["strenum"].initial)
    await assert_val_reading(everything_device.int8, esi["int8"].initial)
    await assert_val_reading(everything_device.uint8, esi["uint8"].initial)
    await assert_val_reading(everything_device.int16, esi["int16"].initial)
    await assert_val_reading(everything_device.uint16, esi["uint16"].initial)
    await assert_val_reading(everything_device.int32, esi["int32"].initial)
    await assert_val_reading(everything_device.uint32, esi["uint32"].initial)
    await assert_val_reading(everything_device.int64, esi["int64"].initial)
    await assert_val_reading(everything_device.uint64, esi["uint64"].initial)
    await assert_val_reading(everything_device.float32, esi["float32"].initial)
    await assert_val_reading(everything_device.float64, esi["float64"].initial)
    await assert_val_reading(everything_device.my_state, esi["my_state"].initial)

    await assert_val_reading(
        everything_device.str_spectrum, esi["str_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.bool_spectrum, esi["bool_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.strenum_spectrum, esi["strenum_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.int8_spectrum, esi["int8_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.uint8_spectrum, esi["uint8_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.int16_spectrum, esi["int16_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.uint16_spectrum, esi["uint16_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.int32_spectrum, esi["int32_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.uint32_spectrum, esi["uint32_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.int64_spectrum, esi["int64_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.uint64_spectrum, esi["uint64_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.float32_spectrum, esi["float32_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.float64_spectrum, esi["float64_spectrum"].initial
    )
    await assert_val_reading(
        everything_device.my_state_spectrum, esi["my_state_spectrum"].initial
    )

    await assert_val_reading(everything_device.str_image, esi["str_image"].initial)
    await assert_val_reading(everything_device.bool_image, esi["bool_image"].initial)
    await assert_val_reading(
        everything_device.strenum_image, esi["strenum_image"].initial
    )
    await assert_val_reading(everything_device.int8_image, esi["int8_image"].initial)
    await assert_val_reading(everything_device.uint8_image, esi["uint8_image"].initial)
    await assert_val_reading(everything_device.int16_image, esi["int16_image"].initial)
    await assert_val_reading(
        everything_device.uint16_image, esi["uint16_image"].initial
    )
    await assert_val_reading(everything_device.int32_image, esi["int32_image"].initial)
    await assert_val_reading(
        everything_device.uint32_image, esi["uint32_image"].initial
    )
    await assert_val_reading(everything_device.int64_image, esi["int64_image"].initial)
    await assert_val_reading(
        everything_device.uint64_image, esi["uint64_image"].initial
    )
    await assert_val_reading(
        everything_device.float32_image, esi["float32_image"].initial
    )
    await assert_val_reading(
        everything_device.float64_image, esi["float64_image"].initial
    )
    await assert_val_reading(
        everything_device.my_state_image, esi["my_state_image"].initial
    )
