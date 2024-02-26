import time

import pytest

from typing import get_type_hints, Any, Optional, Tuple, Type
from enum import Enum, IntEnum

import numpy as np
import numpy.typing as npt

from tango import AttrQuality, AttrDataFormat, AttrWriteType, DeviceProxy, DevState, CmdArgType
from tango.test_utils import assert_close
from tango.server import Device, attribute, command
from tango.asyncio_executor import set_global_executor
from tango.test_context import MultiDeviceTestContext

from ophyd_async.tango._backend._tango_transport import get_pyton_type
from ophyd_async.tango.device import TangoStandardReadableDevice, ReadableSignal
from ophyd_async.core import DeviceCollector, T


class TestEnum(IntEnum):
    __test__ = False
    A = 0
    B = 1


# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------
class TestDevice(Device):
    __test__ = False

    _array = [[1, 2, 3],
              [4, 5, 6]]

    _limitedvalue = 3

    @attribute(dtype=int)
    def justvalue(self):
        return 5

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               dformat=AttrDataFormat.IMAGE, max_dim_x=3, max_dim_y=2)
    def array(self) -> list[list[float]]:
        return self._array

    def write_array(self, array: list[list[float]]):
        self._array = array

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               min_value=0, min_alarm=1, min_warning=2,
               max_warning=4, max_alarm=5, max_value=6)
    def limitedvalue(self) -> float:
        return self._limitedvalue

    def write_limitedvalue(self, value: float):
        self._limitedvalue = value


# --------------------------------------------------------------------
def get_test_descriptor(python_type: Type[T], value: T, is_cmd: bool) -> dict:
    if python_type in [bool, int]:
        return dict(dtype="integer", shape=[])
    if python_type in [float]:
        return dict(dtype="number", shape=[])
    if python_type in [str]:
        return dict(dtype="string", shape=[])
    if issubclass(python_type, DevState):
        return dict(dtype="string", shape=[], choices=list(DevState.names.keys()))
    if issubclass(python_type, Enum):
        return dict(dtype="string", shape=[], choices=[] if is_cmd else [member.name for member in value.__class__])

    return dict(dtype="array", shape=[np.Inf] if is_cmd else list(np.array(value).shape))


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device():
    with MultiDeviceTestContext(
            [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}], process=True) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
class TestReadableDevice(TangoStandardReadableDevice):
    __test__ = False
    justvalue: ReadableSignal[int]
    array: ReadableSignal[npt.NDArray[float]]
    limitedvalue: ReadableSignal[float]


# --------------------------------------------------------------------
def describe_class(cls, fqtrl):
    description = {}
    values = {}
    dev = DeviceProxy(fqtrl)
    hints = get_type_hints(cls)
    for name, dtype in hints.items():
        if name in dev.get_attribute_list():
            attr_conf = dev.get_attribute_config(name)
            value = dev.read_attribute(name).value
            _, _, descr = get_pyton_type(attr_conf.data_type)
            max_x = attr_conf.max_dim_x
            max_y = attr_conf.max_dim_y
            if attr_conf.data_format == AttrDataFormat.SCALAR:
                is_array = False
                shape = []
            elif attr_conf.data_format == AttrDataFormat.SPECTRUM:
                is_array = True
                shape = [max_x]
            else:
                is_array = True
                shape = [max_y, max_x]

        elif name in dev.get_command_list():
            cmd_conf = dev.get_command_config(name)
            _, _, descr = get_pyton_type(cmd_conf.in_type if cmd_conf.in_type != CmdArgType.DevVoid else cmd_conf.out_type)
            shape = []
            is_array = False
            value = getattr(dev, name)()

        else:
            raise RuntimeError(f"{name} cannot be found in {cls} attributes/commands")

        description[f"test_device-{name}"] = {'source': f'{fqtrl}/{name}',  # type: ignore
                                              'dtype': 'array' if is_array else descr,
                                              'shape': shape}

        values[f"test_device-{name}"] = {'value': value,
                                         'timestamp': pytest.approx(time.time()),
                                         'alarm_severity': AttrQuality.ATTR_VALID}

    return values, description


# --------------------------------------------------------------------
def compare_values(expected, received):
    assert set(list(expected.keys())) == set(list(received.keys()))
    for k, v in expected.items():
        for _k, _v in v.items():
            assert_close(_v, received[k][_k])


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect(tango_test_device):
    values, description = describe_class(TestReadableDevice(""), tango_test_device)

    async with DeviceCollector():
        test_device = await TestReadableDevice(tango_test_device)

    assert test_device.name == "test_device"
    assert description == await test_device.describe()
    compare_values(values, await test_device.read())
