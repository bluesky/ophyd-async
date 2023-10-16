import pytest
import asyncio
import time

import numpy as np
import numpy.typing as npt

from typing import Any, Optional, Tuple, Type

from enum import Enum, IntEnum

from tango import AttrWriteType, AttrDataFormat, DeviceProxy, DevState
from tango.server import Device, attribute
from tango.test_utils import assert_close
from tango.test_context import MultiDeviceTestContext
from tango.asyncio_executor import set_global_executor

from bluesky.protocols import Reading

from ophyd_async.core import SignalBackend, T
from ophyd_async.tango._backend import TangoTransport


# --------------------------------------------------------------------
"""
Since TangoTest does not support EchoMode, we create our own Device.

"""


class TestEnum(IntEnum):
    A = 0
    B = 1


def get_enum_labels(enum_cls):
    if enum_cls == DevState:
        return list(enum_cls.names.keys())
    else:
        return [member.name for member in enum_cls]


TEST_ENUM_CLASS_LABELS = get_enum_labels(TestEnum)


TYPES_TO_TEST = (
                 ("boolean_scalar", 'DevBoolean', AttrDataFormat.SCALAR, bool, True, False),
                 ("boolean_spectrum", 'DevBoolean', AttrDataFormat.SPECTRUM, npt.NDArray[np.bool_], [True, False], [False, True]),
                 ("boolean_image", 'DevBoolean', AttrDataFormat.IMAGE, npt.NDArray[np.bool_], [[True, False], [False, True]],
                  np.array([[False, True], [True, False]])),

                 ("short_scalar", 'DevShort', AttrDataFormat.SCALAR, int, 1, 2),
                 ("short_spectrum", 'DevShort', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("short_image", 'DevShort', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("long_scalar", 'DevLong', AttrDataFormat.SCALAR, int, 1, 2),
                 ("long_spectrum", 'DevLong', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("long_image", 'DevLong', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("ushort_scalar", 'DevUShort', AttrDataFormat.SCALAR, int, 1, 2),
                 ("ushort_spectrum", 'DevUShort', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("ushort_image", 'DevUShort', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("ulong_scalar", 'DevLong', AttrDataFormat.SCALAR, int, 1, 2),
                 ("ulong_spectrum", 'DevLong', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("ulong_image", 'DevLong', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("ulong64_scalar", 'DevULong64', AttrDataFormat.SCALAR, int, 1, 2),
                 ("ulong64_spectrum", 'DevULong64', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("ulong64_image", 'DevULong64', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("long64_scalar", 'DevLong64', AttrDataFormat.SCALAR, int, 1, 2),
                 ("long64_spectrum", 'DevLong64', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("long64_image", 'DevLong64', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("char_scalar", 'DevUChar', AttrDataFormat.SCALAR, int, 1, 2),
                 ("char_spectrum", 'DevUChar', AttrDataFormat.SPECTRUM, npt.NDArray[np.int_], [1, 2], [3, 4]),
                 ("char_image", 'DevUChar', AttrDataFormat.IMAGE, npt.NDArray[np.int_], [[1, 2], [3, 4]], [[5, 6], [7, 8]]),

                 ("float_scalar", 'DevFloat', AttrDataFormat.SCALAR, float, 1.1, 2.2),
                 ("float_spectrum", 'DevFloat', AttrDataFormat.SPECTRUM, npt.NDArray[np.float_], [1.1, 2.2], [3.3, 4.4]),
                 ("float_image", 'DevFloat', AttrDataFormat.IMAGE, npt.NDArray[np.float_], [[1.1, 2.2], [3.3, 4.4]],
                  [[5.5, 6.6], [7.7, 8.8]]),

                 ("double_scalar", 'DevDouble', AttrDataFormat.SCALAR, float, 1.1, 2.2),
                 ("double_spectrum", 'DevDouble', AttrDataFormat.SPECTRUM, npt.NDArray[np.float_], [1.1, 2.2], [3.3, 4.4]),
                 ("double_image", 'DevDouble', AttrDataFormat.IMAGE, npt.NDArray[np.float_], [[1.1, 2.2], [3.3, 4.4]],
                  [[5.5, 6.6], [7.7, 8.8]]),

                 ("string_scalar", 'DevString', AttrDataFormat.SCALAR, str, "aaa", "bbb"),
                 ("string_spectrum", 'DevString', AttrDataFormat.SPECTRUM, npt.NDArray[str], ["aaa", "bbb"], ["ccc", "ddd"]),
                 ("string_image", 'DevString', AttrDataFormat.IMAGE, npt.NDArray[str], [["aaa", "bbb"], ["ccc", "ddd"]],
                  [["eee", "fff"], ["ggg", "hhh"]]),

                 ("state_scalar", 'DevState', AttrDataFormat.SCALAR, DevState, DevState.ON, DevState.OFF),
                 ("state_spectrum", 'DevState', AttrDataFormat.SPECTRUM, npt.NDArray[DevState], [DevState.ON, DevState.OFF],
                  [DevState.OFF, DevState.ON]),
                 ("state_image", 'DevState', AttrDataFormat.IMAGE, npt.NDArray[DevState],
                  [[DevState.ON, DevState.OFF], [DevState.OFF, DevState.ON]],
                  [[DevState.OFF, DevState.ON], [DevState.ON, DevState.OFF]]),

                  ("enum_scalar", 'DevEnum', AttrDataFormat.SCALAR, TestEnum, TestEnum.A, TestEnum.B),
                  ("enum_spectrum", 'DevEnum', AttrDataFormat.SPECTRUM, npt.NDArray[TestEnum], [TestEnum.A, TestEnum.B],
                   [TestEnum.B, TestEnum.A]),
                  ("enum_image", 'DevEnum', AttrDataFormat.IMAGE, npt.NDArray[TestEnum],
                   [[TestEnum.A, TestEnum.B], [TestEnum.B, TestEnum.A]],
                   [[TestEnum.B, TestEnum.A], [TestEnum.A, TestEnum.B]]),

                 # ('DevEncoded': tango._tango.CmdArgType.DevEncoded,
                 )


# --------------------------------------------------------------------
#               Echo device
# --------------------------------------------------------------------
class EchoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        for name, typ, form, _, _, _ in TYPES_TO_TEST:
            attr = attribute(
                name=name,
                dtype=typ,
                dformat=form,
                access=AttrWriteType.READ_WRITE,
                fget=self.read,
                fset=self.write,
                max_dim_x=2,
                max_dim_y=2,
                enum_labels=TEST_ENUM_CLASS_LABELS
            )
            self.add_attribute(attr)
            self.set_change_event(name, True, False)

    def read(self, attr):
        attr.set_value(self.attr_values[attr.get_name()])

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)


# --------------------------------------------------------------------
def assert_enum(initial_value, readout_value):
    if type(readout_value) in [list, tuple]:
        for _initial_value, _readout_value in zip(initial_value, readout_value):
            assert_enum(_initial_value, _readout_value)
    else:
        assert initial_value == readout_value

# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------
@pytest.fixture(scope="session")
def echo_device():
    with MultiDeviceTestContext([{"class": EchoDevice, "devices": [{"name": "test/device/1"}]}], process=True) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
#               helpers to run tests
# --------------------------------------------------------------------
def get_test_descriptor(python_type: Type[T], value: T) -> dict:
    if python_type in [bool, int]:
        return dict(dtype="integer", shape=[])
    if python_type in [float]:
        return dict(dtype="number", shape=[])
    if python_type in [str]:
        return dict(dtype="string", shape=[])
    if issubclass(python_type, (Enum, DevState)):
        return dict(dtype="string", shape=[], choices=get_enum_labels(value.__class__))

    return dict(dtype="array", shape=list(np.array(value).shape))


# --------------------------------------------------------------------
async def make_backend(typ: Optional[Type], pv: str, connect=True) -> SignalBackend:
    backend = TangoTransport(typ, pv, pv)
    if connect:
        await asyncio.wait_for(backend.connect(), 10)
    return backend


# --------------------------------------------------------------------
def prepare_device(echo_device: str, pv: str, put_value: T) -> None:
    setattr(DeviceProxy(echo_device), pv, put_value)


# --------------------------------------------------------------------
class MonitorQueue:
    def __init__(self, backend: SignalBackend):
        self.backend = backend
        self.subscription = backend.set_callback(self.add_reading_value)
        self.updates: asyncio.Queue[Tuple[Reading, Any]] = asyncio.Queue()

    def add_reading_value(self, reading: Reading, value):
        self.updates.put_nowait((reading, value))

    async def assert_updates(self, expected_value):
        expected_reading = {
            "timestamp": pytest.approx(time.time(), rel=0.1),
            "alarm_severity": 0,
        }
        update_reading, update_value = await self.updates.get()
        get_reading = await self.backend.get_reading()
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
        datatype: Optional[Type[T]] = None,
):
    prepare_device(echo_device, pv, initial_value)
    source = echo_device + '/' + pv
    backend = await make_backend(datatype, source)
    # Make a monitor queue that will monitor for updates
    q = MonitorQueue(backend)
    try:
        assert dict(source=source, **descriptor) == await backend.get_descriptor()
        # Check initial value
        await q.assert_updates(initial_value)
        # Put to new value and check that
        await backend.put(put_value)
        await q.assert_updates(put_value)
    finally:
        q.close()


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("pv, tango_type, d_format, py_type, initial_value, put_value", TYPES_TO_TEST)
async def test_backend_get_put_monitor(echo_device: str,
                                       pv: str,
                                       tango_type: str,
                                       d_format: AttrDataFormat,
                                       py_type: Type[T],
                                       initial_value: T,
                                       put_value: T):
    # With the given datatype, check we have the correct initial value and putting
    # works
    descriptor = get_test_descriptor(py_type, initial_value)
    await assert_monitor_then_put(echo_device, pv, initial_value, put_value, descriptor, py_type)
    # # With datatype guessed from CA/PVA, check we can set it back to the initial value
    await assert_monitor_then_put(echo_device, pv, initial_value, put_value, descriptor, datatype=None)
