import time
from enum import Enum, IntEnum
from typing import Type

import numpy as np
import pytest
from bluesky import RunEngine
from bluesky.plans import count

from ophyd_async.core import DeviceCollector, T
from ophyd_async.tango import TangoReadableDevice, tango_signal_auto
from ophyd_async.tango._backend._tango_transport import get_python_type
from tango import (
    AttrDataFormat,
    AttrQuality,
    AttrWriteType,
    CmdArgType,
    # DeviceProxy,
    DevState,
)
from tango.asyncio import DeviceProxy
from tango.asyncio_executor import set_global_executor
from tango.server import Device, attribute, command
from tango.test_context import MultiDeviceTestContext
from tango.test_utils import assert_close


class TestEnum(IntEnum):
    __test__ = False
    A = 0
    B = 1


# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------

TESTED_FEATURES = ["array", "limitedvalue", "justvalue"]


class TestDevice(Device):
    __test__ = False

    _array = [[1, 2, 3], [4, 5, 6]]

    _justvalue = 5
    _writeonly = 6
    _readonly = 7

    _limitedvalue = 3

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, polling_period=100)
    def justvalue(self):
        return self._justvalue

    def write_justvalue(self, value: int):
        self._justvalue = value

    @attribute(dtype=int, access=AttrWriteType.WRITE, polling_period=100)
    def writeonly(self):
        return self._writeonly

    def write_writeonly(self, value: int):
        self._writeonly = value

    @attribute(dtype=int, access=AttrWriteType.READ, polling_period=100)
    def readonly(self):
        return self._readonly

    @attribute(
        dtype=float,
        access=AttrWriteType.READ_WRITE,
        dformat=AttrDataFormat.IMAGE,
        max_dim_x=3,
        max_dim_y=2,
    )
    def array(self) -> list[list[float]]:
        return self._array

    def write_array(self, array: list[list[float]]):
        self._array = array

    @attribute(
        dtype=float,
        access=AttrWriteType.READ_WRITE,
        min_value=0,
        min_alarm=1,
        min_warning=2,
        max_warning=4,
        max_alarm=5,
        max_value=6,
    )
    def limitedvalue(self) -> float:
        return self._limitedvalue

    def write_limitedvalue(self, value: float):
        self._limitedvalue = value

    @command
    def clear(self) -> str:
        # self.info_stream("Received clear command")
        return "Received clear command"


# --------------------------------------------------------------------
class TestReadableDevice(TangoReadableDevice):
    __test__ = False

    def __init__(self, trl: str, name="") -> None:
        self.trl = trl
        for feature in TESTED_FEATURES:
            with self.add_children_as_readables():
                setattr(self, feature, tango_signal_auto(None, f"{trl}/{feature}"))
        TangoReadableDevice.__init__(self, trl, name)


# --------------------------------------------------------------------
async def describe_class(fqtrl):
    description = {}
    values = {}
    dev = await DeviceProxy(fqtrl)

    for name in TESTED_FEATURES:
        if name in dev.get_attribute_list():
            attr_conf = await dev.get_attribute_config(name)
            attr_value = await dev.read_attribute(name)
            value = attr_value.value
            _, _, descr = get_python_type(attr_conf.data_type)
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
            cmd_conf = await dev.get_command_config(name)
            _, _, descr = get_python_type(
                cmd_conf.in_type
                if cmd_conf.in_type != CmdArgType.DevVoid
                else cmd_conf.out_type
            )
            is_array = False
            shape = []
            value = getattr(dev, name)()

        else:
            raise RuntimeError(
                f"Cannot find {name} in attributes/commands (pipes are not supported!)"
            )

        description[f"test_device-{name}"] = {
            "source": f"{fqtrl}/{name}",  # type: ignore
            "dtype": "array" if is_array else descr,
            "shape": shape,
        }

        values[f"test_device-{name}"] = {
            "value": value,
            "timestamp": pytest.approx(time.time()),
            "alarm_severity": AttrQuality.ATTR_VALID,
        }

    return values, description


# --------------------------------------------------------------------
def get_test_descriptor(python_type: Type[T], value: T, is_cmd: bool) -> dict:
    if python_type in [bool, int]:
        return {"dtype": "integer", "shape": []}
    if python_type in [float]:
        return {"dtype": "number", "shape": []}
    if python_type in [str]:
        return {"dtype": "string", "shape": []}
    if issubclass(python_type, DevState):
        return {"dtype": "string", "shape": [], "choices": list(DevState.names.keys())}
    if issubclass(python_type, Enum):
        return {
            "dtype": "string",
            "shape": [],
            "choices": [] if is_cmd else [member.name for member in python_type],
        }

    return {
        "dtype": "array",
        "shape": [np.Inf] if is_cmd else list(np.array(value).shape),
    }


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def tango_test_device():
    with MultiDeviceTestContext(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}], process=True
    ) as context:
        yield context.get_device_access("test/device/1")


# --------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


# --------------------------------------------------------------------
def compare_values(expected, received):
    assert set(expected.keys()) == set(received.keys())
    for k, v in expected.items():
        for _k, _v in v.items():
            assert_close(_v, received[k][_k])


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connect(tango_test_device):
    values, description = await describe_class(tango_test_device)

    async with DeviceCollector():
        test_device = TestReadableDevice(tango_test_device)

    assert test_device.name == "test_device"
    assert description == await test_device.describe()
    compare_values(values, await test_device.read())


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_with_bluesky(tango_test_device):
    async def connect():
        async with DeviceCollector():
            device = TestReadableDevice(tango_test_device)
            return device

    ophyd_dev = await connect()

    # now let's do some bluesky stuff
    RE = RunEngine()
    RE(count([ophyd_dev], 1))
