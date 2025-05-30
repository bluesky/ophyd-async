import asyncio
import time
from enum import Enum, IntEnum
from typing import Annotated as A
from typing import TypeVar

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import numpy as np
import pytest
import tango
from bluesky import RunEngine
from tango import (
    AttrDataFormat,
    AttrQuality,
    AttrWriteType,
    CmdArgType,
    DevState,
)
from tango.asyncio import DeviceProxy as AsyncDeviceProxy
from tango.server import Device, attribute, command

from ophyd_async.core import Array1D, Ignore, SignalRW, init_devices
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import TangoReadable, get_full_attr_trl, get_python_type
from ophyd_async.tango.demo import (
    DemoCounter,
    DemoMover,
    TangoDetector,
)
from ophyd_async.testing import assert_reading

T = TypeVar("T")


class TestEnum(IntEnum):
    __test__ = False
    A = 0
    B = 1


# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------

TESTED_FEATURES = ["array", "limitedvalue", "justvalue"]


# --------------------------------------------------------------------
class TestDevice(Device):
    __test__ = False

    _array = [[1, 2, 3], [4, 5, 6]]

    _justvalue = 5
    _writeonly = 6
    _readonly = 7
    _slow_attribute = 1.0

    _floatvalue = 1.0

    _readback = 1.0
    _setpoint = 1.0

    _label = "Test Device"

    _limitedvalue = 3

    _ignored_attr = 1.0

    @attribute(dtype=float, access=AttrWriteType.READ)
    def readback(self):
        return self._readback

    @attribute(dtype=float, access=AttrWriteType.WRITE)
    def setpoint(self):
        return self._setpoint

    def write_setpoint(self, value: float):
        self._setpoint = value
        self._readback = value

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
    def label(self):
        return self._label

    def write_label(self, value: str):
        self._label = value

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    def floatvalue(self):
        return self._floatvalue

    def write_floatvalue(self, value: float):
        self._floatvalue = value

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

    @attribute(dtype=float, access=AttrWriteType.WRITE)
    def slow_attribute(self) -> float:
        return self._slow_attribute

    def write_slow_attribute(self, value: float):
        time.sleep(0.2)
        self._slow_attribute = value

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    def raise_exception_attr(self) -> float:
        raise

    def write_raise_exception_attr(self, value: float):
        raise

    @attribute(dtype=float, access=AttrWriteType.READ)
    def ignored_attr(self) -> float:
        return self._ignored_attr

    @command
    def clear(self) -> str:
        # self.info_stream("Received clear command")
        return "Received clear command"

    @command
    def slow_command(self) -> str:
        time.sleep(0.2)
        return "Completed slow command"

    @command
    def echo(self, value: str) -> str:
        return value

    @command
    def raise_exception_cmd(self):
        raise


# --------------------------------------------------------------------
class TestTangoReadable(TangoReadable):
    __test__ = False
    justvalue: A[SignalRW[int], Format.HINTED_UNCACHED_SIGNAL]
    array: A[SignalRW[Array1D[np.float64]], Format.HINTED_UNCACHED_SIGNAL]
    limitedvalue: A[SignalRW[float], Format.HINTED_UNCACHED_SIGNAL]
    ignored_attr: Ignore


# --------------------------------------------------------------------
async def describe_class(fqtrl):
    description = {}
    values = {}
    dev = await AsyncDeviceProxy(fqtrl)

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
            "source": get_full_attr_trl(fqtrl, name),
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
def get_test_descriptor(python_type: type[T], value: T, is_cmd: bool) -> dict:
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
def tango_test_device(subprocess_helper):
    with subprocess_helper(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}]
    ) as context:
        yield context.trls["test/device/1"]


# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def sim_test_context_trls(subprocess_helper):
    args = (
        {
            "class": DemoMover,
            "devices": [{"name": "sim/motor/1"}],
        },
        {
            "class": DemoCounter,
            "devices": [{"name": "sim/counter/1"}, {"name": "sim/counter/2"}],
        },
    )
    with subprocess_helper(args) as context:
        yield context.trls


# --------------------------------------------------------------------


@pytest.mark.timeout(8.0)
@pytest.mark.asyncio
async def test_connect(tango_test_device):
    values, description = await describe_class(tango_test_device)
    async with init_devices():
        test_device = TestTangoReadable(tango_test_device)

    assert test_device.name == "test_device"
    assert description == await test_device.describe()
    await assert_reading(test_device, values)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_trl(tango_test_device):
    values, description = await describe_class(tango_test_device)
    test_device = TestTangoReadable(name="test_device")

    test_device._connector.trl = tango_test_device
    await test_device.connect()

    assert test_device.name == "test_device"
    assert description == await test_device.describe()
    await assert_reading(test_device, values)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("use_trl", [True, False])
async def test_connect_proxy(tango_test_device, use_trl: str | None):
    if use_trl:
        test_device = TestTangoReadable(trl=tango_test_device)
        test_device.proxy = None
        await test_device.connect()
        assert isinstance(test_device._connector.proxy, tango._tango.DeviceProxy)
    else:
        test_device = TestTangoReadable()
        assert test_device


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_with_bluesky(tango_test_device):
    # now let's do some bluesky stuff
    RE = RunEngine()
    with init_devices():
        device = TestTangoReadable(tango_test_device)
    RE(bp.count([device]))


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(15.5)
async def test_tango_sim(sim_test_context_trls):
    detector = TangoDetector(
        name="detector",
        mover_trl=sim_test_context_trls["sim/motor/1"],
        counter_trls=[
            sim_test_context_trls["sim/counter/1"],
            sim_test_context_trls["sim/counter/2"],
        ],
    )
    await detector.connect()
    await detector.trigger()
    await detector.mover.velocity.set(0.5)

    RE = RunEngine()

    RE(bps.read(detector))
    RE(bps.mv(detector, 0))
    RE(bp.count(list(detector.counters.values())))

    set_status = detector.set(1.0)
    await asyncio.sleep(1.0)
    stop_status = detector.stop()
    await set_status
    await stop_status
    assert all([set_status.done, stop_status.done])
    assert all([set_status.success, stop_status.success])


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_fill_signals", [True, False])
@pytest.mark.timeout(8.8)
async def test_signal_autofill(tango_test_device, auto_fill_signals):
    test_device = TestTangoReadable(
        trl=tango_test_device, auto_fill_signals=auto_fill_signals
    )
    await test_device.connect()
    if auto_fill_signals:
        assert not hasattr(test_device, "ignored_attr")
        assert hasattr(test_device, "readback")
    else:
        assert not hasattr(test_device, "ignored_attr")
        assert not hasattr(test_device, "readback")
