"""Every Tango device server this repo ships for testing/demoing ophyd-async.

Kept as a single, self-contained module (not a package) so it stays trivially
importable/runnable on its own from a plain PyTango environment - it needs
`tango`/`tango.server` but nothing from `ophyd_async.tango.core` (the ophyd-async
client connection machinery, needed instead by the declarative `TangoTestDevice`
in `ophyd_async.tango.testing._test_device`) and nothing from `ophyd_async.testing`
(which pulls in `bluesky`/`event_model`/`pytest` - `int_array_value`/
`float_array_value` are duplicated locally below rather than imported, for exactly
this reason; `ophyd_async.testing.float_array_value`/`int_array_value` are the
source of truth other transports' test devices should still prefer where they
don't have this constraint).

All of these devices are served together, at fixed, predictable names, by
`_tango_device_servers.py` - see that module for how to actually run them up.
Three groups, in the order they appear below:

- `OneOfEverythingTangoDevice`: the datatype-coverage matrix (paired with the
  declarative `TangoTestDevice`).
- `TestDevice`: lower-level signal-transport/edge-case coverage (polling vs
  events, read-only/write-only, error paths, ...), used directly with
  `tango_signal_r`/`tango_signal_rw`/`tango_signal_w` rather than a declarative
  Device.
- `DemoMotorDevice`/`DemoPointDetectorChannelDevice`/`DemoMultiChannelDetectorDevice`:
  backs the `ophyd_async.tango.demo` tutorial Devices (`DemoMotor`, `DemoStage`,
  `DemoPointDetector`, `DemoPointDetectorChannel`). Lives here, not in
  `ophyd_async.tango.demo`, so the one fixed topology `_tango_device_servers.py`
  serves is usable both by the tutorial and by structural tests
  (`tests/system_tests_tango/test_base_device.py`) - there's no good reason for
  those to instantiate different topologies of the same devices.
"""

import asyncio
import math
import time
import types
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Generic, TypeVar

import numpy as np
import tango
from tango import AttrDataFormat, AttrWriteType, CmdArgType, DevState, GreenMode
from tango.asyncio import DeviceProxy
from tango.server import Device, attribute, command, device_property

from ophyd_async.core import Array1D, DTypeScalar_co

from ._example_types import ExampleStrEnum

T = TypeVar("T")


def int_array_value(dtype: type[DTypeScalar_co]):
    iinfo = np.iinfo(dtype)  # type: ignore
    return np.array([iinfo.min, iinfo.max, 0, 1, 2, 3, 4], dtype=dtype)


def float_array_value(dtype: type[DTypeScalar_co]):
    finfo = np.finfo(dtype)  # type: ignore
    return np.array(
        [
            finfo.min,
            finfo.max,
            finfo.smallest_normal,
            finfo.smallest_subnormal,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=dtype,
    )


def _make_echo_command(cmd_name: str):
    """Build an identity/echo command function with the given Tango command name.

    Tango's `command()` derives the served command name from `f.__name__`, so each
    dynamically-registered echo command needs its own uniquely-named callable.
    """

    def echo(self, arg):
        return arg

    echo.__name__ = cmd_name
    return echo


def int_image_value(
    dtype: type[DTypeScalar_co],
):
    # how do we type this?
    array_1d = int_array_value(dtype)
    return np.vstack((array_1d, array_1d))


def float_image_value(
    dtype: type[DTypeScalar_co],
):
    # how do we type this?
    array_1d = float_array_value(dtype)
    return np.vstack((array_1d, array_1d))


def _valid_command(dformat: AttrDataFormat, dtype: str):
    if dformat != AttrDataFormat.SCALAR and dtype in ["DevState", "DevEnum"]:
        return False
    return True


@dataclass
class AttributeData(Generic[T]):
    name: str
    tango_type: str
    initial_scalar: T
    initial_spectrum: Array1D | Sequence[T]


_all_attribute_definitions = [
    AttributeData(
        # Named a_str, not str, to avoid shadowing the builtin as a Python identifier
        "a_str",
        "DevString",
        "test_string",
        ["one", "two", "three"],
    ),
    AttributeData(
        # Named a_bool, not bool, to avoid shadowing the builtin as a Python identifier
        "a_bool",
        "DevBoolean",
        True,
        np.array([False, True], dtype=bool),
    ),
    AttributeData("strenum", "DevEnum", 1, np.array([0, 1, 2])),
    AttributeData("int8", "DevShort", 1, int_array_value(np.int8)),
    AttributeData("uint8", "DevUChar", 1, int_array_value(np.uint8)),
    AttributeData("int16", "DevShort", 1, int_array_value(np.int16)),
    AttributeData("uint16", "DevUShort", 1, int_array_value(np.uint16)),
    AttributeData("int32", "DevLong", 1, int_array_value(np.int32)),
    AttributeData("uint32", "DevULong", 1, int_array_value(np.uint32)),
    AttributeData("int64", "DevLong64", 1, int_array_value(np.int64)),
    AttributeData("uint64", "DevULong64", 1, int_array_value(np.uint64)),
    AttributeData("float32", "DevFloat", 1.234, float_array_value(np.float32)),
    AttributeData("float64", "DevDouble", 1.234, float_array_value(np.float64)),
    AttributeData(
        "my_state",
        "DevState",
        DevState.INIT,
        np.array(list(DevState.names.values()), dtype=DevState),  # type: ignore
    ),
]


class OneOfEverythingTangoDevice(Device):
    attr_values = {}
    initial_values = {}

    def _add_attr(self, attr: attribute, initial_value):
        self.attr_values[attr.name] = initial_value
        self.initial_values[attr.name] = initial_value
        self.add_attribute(attr)
        self.set_change_event(attr.name, True, False)

    def add_scalar_attr(self, name: str, dtype: str, initial_value: Any):
        attr = attribute(
            name=name,
            dtype=dtype,
            dformat=AttrDataFormat.SCALAR,
            access=AttrWriteType.READ_WRITE,
            fget=self.read,
            fset=self.write,
            enum_labels=[e.value for e in ExampleStrEnum],
        )
        self._add_attr(attr, initial_value)

    def long_string_cmd(self, arg):
        """Echo command for DevVarLongStringArray."""
        return arg

    def double_string_cmd(self, arg):
        """Echo command for DevVarDoubleStringArray."""
        return arg

    def void_cmd(self):
        """Command for DevVoid."""
        return

    def add_array_attrs(self, name: str, dtype: str, initial_value: np.ndarray):
        spectrum_name = f"{name}_spectrum"
        if hasattr(initial_value, "shape"):
            max_dim_x = initial_value.shape[-1]
        else:
            max_dim_x = len(initial_value)
        spectrum_attr = attribute(
            name=spectrum_name,
            dtype=dtype,
            dformat=AttrDataFormat.SPECTRUM,
            access=AttrWriteType.READ_WRITE,
            fget=self.read,
            fset=self.write,
            max_dim_x=max_dim_x,
            enum_labels=[e.value for e in ExampleStrEnum],
        )
        image_name = f"{name}_image"
        image_attr = attribute(
            name=image_name,
            dtype=dtype,
            dformat=AttrDataFormat.IMAGE,
            access=AttrWriteType.READ_WRITE,
            fget=self.read,
            fset=self.write,
            max_dim_x=max_dim_x,
            max_dim_y=2,
            enum_labels=[e.value for e in ExampleStrEnum],
        )
        # Arrays of enums are not supported, do not add their attribute data
        if name in ["strenum", "my_state"]:
            return
        self._add_attr(spectrum_attr, initial_value)
        # have image just be 2 of the initial spectrum stacked
        # String images are not supported, do not add their attribute data
        if name in ["a_str"]:
            return
        self._add_attr(image_attr, np.vstack((initial_value, initial_value)))

        void_cmd = command(
            f=self.void_cmd,
            dtype_in=CmdArgType.DevVoid,
            dtype_out=CmdArgType.DevVoid,
        )

        long_string_table_cmd = command(
            f=self.long_string_cmd,
            dtype_in=CmdArgType.DevVarLongStringArray,
            dtype_out=CmdArgType.DevVarLongStringArray,
        )
        double_string_table_cmd = command(
            f=self.double_string_cmd,
            dtype_in=CmdArgType.DevVarDoubleStringArray,
            dtype_out=CmdArgType.DevVarDoubleStringArray,
        )
        self.add_command(void_cmd)
        self.add_command(long_string_table_cmd)
        self.add_command(double_string_table_cmd)

    def _add_echo_command(
        self,
        cmd_name: str,
        dtype_in,
        dtype_out,
        dformat_in: AttrDataFormat | None = None,
        dformat_out: AttrDataFormat | None = None,
    ):
        self.add_command(
            command(
                f=types.MethodType(_make_echo_command(cmd_name), self),
                dtype_in=dtype_in,
                dtype_out=dtype_out,
                dformat_in=dformat_in,
                dformat_out=dformat_out,
            ),
        )

    def add_scalar_command(self, name: str, dtype: str):
        if _valid_command(AttrDataFormat.SCALAR, dtype):
            self._add_echo_command(
                f"{name}_cmd",
                dtype,
                dtype,
                AttrDataFormat.SCALAR,
                AttrDataFormat.SCALAR,
            )

    def add_spectrum_command(self, name: str, dtype: str):
        if _valid_command(AttrDataFormat.SPECTRUM, dtype):
            cmd_name = f"{name}_spectrum_cmd"
            if name in ["int8", "uint8"]:
                self._add_echo_command(
                    cmd_name, CmdArgType.DevVarCharArray, CmdArgType.DevVarCharArray
                )
            else:
                self._add_echo_command(
                    cmd_name,
                    dtype,
                    dtype,
                    AttrDataFormat.SPECTRUM,
                    AttrDataFormat.SPECTRUM,
                )

    def initialize_dynamic_attributes(self):
        for attr_data in _all_attribute_definitions:
            self.add_scalar_attr(
                attr_data.name, attr_data.tango_type, attr_data.initial_scalar
            )
            self.add_array_attrs(
                attr_data.name, attr_data.tango_type, attr_data.initial_spectrum
            )
            self.add_scalar_command(attr_data.name, attr_data.tango_type)
            self.add_spectrum_command(attr_data.name, attr_data.tango_type)

    @command(dtype_in=float, dtype_out=bool)
    def float_to_bool_cmd(self, value: float) -> bool:
        """Command with float input and bool output (different in/out types)."""
        return value > 0

    @command
    def reset_values(self):
        for attr_name in self.attr_values:
            self.attr_values[attr_name] = self.initial_values[attr_name]

    def read(self, attr):
        value = self.attr_values[attr.get_name()]
        attr.set_value(value)

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)


# --------------------------------------------------------------------------
# TestDevice: lower-level signal-transport/edge-case coverage (polling vs
# events, read-only/write-only, error paths, ...). No `set_change_event` calls
# anywhere here (unlike OneOfEverythingTangoDevice above), so attributes that
# need monitor support explicitly set `polling_period` instead.
# --------------------------------------------------------------------------


class TestEnum(IntEnum):
    A = 0
    B = 1


class TestDevice(Device):
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

    _msg = "Hello"

    _test_enum = TestEnum.A
    _string_image = [["one", "two", "three"], ["four", "five", "six"]]
    _long_string_array = ([1, 2, 3], ["one", "two", "three"])
    _sequence = ["one", "two", "three"]

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
        dtype=CmdArgType.DevString,
        access=AttrWriteType.READ_WRITE,
        dformat=AttrDataFormat.SPECTRUM,
        max_dim_x=3,
    )
    def sequence(self):
        return self._sequence

    def write_sequence(self, sequence: list[str]):
        self._sequence = sequence

    @attribute(
        access=AttrWriteType.READ_WRITE,
        min_value=0.0,
        min_alarm=1.0,
        min_warning=2.0,
        max_warning=4.0,
        max_alarm=5.0,
        max_value=6.0,
        unit="cm",
        delta_val="1",
        delta_t="1",
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

    @attribute(
        dtype=tango.CmdArgType.DevEnum,
        enum_labels=["A", "B"],
        access=AttrWriteType.READ,
    )
    def test_enum(self) -> TestEnum:
        return self._test_enum

    @command(
        dtype_out=CmdArgType.DevVarLongStringArray,
    )
    def get_longstringarray(self) -> tuple[list[int], list[str]]:
        return self._long_string_array

    @command(
        dtype_out=CmdArgType.DevVarDoubleStringArray,
    )
    def get_doublestringarray(self) -> tuple[list[float], list[str]]:
        return self._long_string_array

    @command
    def clear(self):
        pass

    @command
    def slow_command(self) -> str:
        time.sleep(0.2)
        return "Completed slow command"

    @command
    def echo(self, value: str) -> str:
        return value

    @command
    def get_msg(self) -> str:
        return self._msg

    @command
    def set_msg(self, value: str):
        self._msg = value

    @command
    def raise_exception_cmd(self):
        raise

    @command(
        dtype_in=CmdArgType.DevEnum,
        dtype_out=CmdArgType.DevEnum,
    )
    def enum_cmd(self, value: TestEnum) -> TestEnum:
        return value


# --------------------------------------------------------------------------
# Demo devices: back the ophyd_async.tango.demo tutorial Devices. See the
# module docstring for why these live here rather than in tango.demo.
# --------------------------------------------------------------------------


class DemoMotorDevice(Device):
    """Demo tango moving device."""

    green_mode = GreenMode.Asyncio
    _position = 0.0
    _setpoint = 0.0
    _velocity = 1.0
    _acceleration = 1.0
    _stop = False
    DEVICE_CLASS_INITIAL_STATE = DevState.ON

    @attribute(dtype=float, access=AttrWriteType.READ, format="%6.3f")
    async def readback(self):
        return self._position

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE, format="%6.3f")
    async def setpoint(self):
        return self._setpoint

    async def write_setpoint(self, new_position):
        self.set_state(DevState.MOVING)
        self._setpoint = new_position
        asyncio.create_task(self.move())

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    async def velocity(self):
        return self._velocity

    async def write_velocity(self, value: float):
        self._velocity = value

    @attribute(dtype=DevState, access=AttrWriteType.READ)
    async def state(self):
        return self.get_state()

    @command
    async def stop(self):
        self._stop = True

    @command
    async def move(self):
        self.set_state(DevState.MOVING)
        self._stop = False
        step = 0.1
        while True:
            if self._stop:
                self._stop = False
                break
            if abs(self._position - self._setpoint) < abs(self._velocity * step):
                self._position = self._setpoint
                break
            if self._position < self._setpoint:
                self._position = self._position + self._velocity * step
            else:
                self._position = self._position - self._velocity * step
            await asyncio.sleep(step)
        self.set_state(DevState.ON)


class Mode(IntEnum):
    LOW = 0
    HIGH = 1


class DemoMultiChannelDetectorDevice(Device):
    """Demo tango counting device."""

    channels = device_property(dtype=int, default_value=0)

    green_mode = GreenMode.Asyncio
    _acquire_time = 0.1
    _acquiring = False
    _elapsed = 0.0

    async def init_device(self):
        await super().init_device()
        self._locators = []
        self._dps = []

    @attribute(dtype=(str,), max_dim_x=32, access=AttrWriteType.READ_WRITE)
    async def locators(self):
        return self._locators

    async def write_locators(self, value: (str)):
        self._locators = value

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    async def acquire_time(self):
        return self._acquire_time

    async def write_acquire_time(self, value: float):
        self._acquire_time = value

    @attribute(dtype=bool, access=AttrWriteType.READ)
    async def acquiring(self):
        return self._acquiring

    @attribute(dtype=float, access=AttrWriteType.READ)
    async def elapsed(self):
        return self._elapsed

    @attribute(dtype=DevState, access=AttrWriteType.READ)
    async def state(self):
        return self.get_state()

    @command
    async def connect_devices(self):
        for locator in self._locators:
            # Connect by tango device proxy to the X motor
            self._dps.append(await DeviceProxy(locator))  # type: ignore

    @command
    async def start(self):
        await self._acquisition()

    @command
    async def reset(self):
        self._elapsed = 0.0

    async def _acquisition(self):
        self._acquiring = True
        self._elapsed = 0.0
        step = 0.1
        while self._elapsed < self._acquire_time:
            self._elapsed += step
            # Send the elapsed update to the channels
            for dps in self._dps:
                dps.elapsed = self._elapsed
            await asyncio.sleep(step)
        self._elapsed = self._acquire_time
        for dps in self._dps:
            dps.elapsed = self._acquire_time
        await asyncio.sleep(step)
        self._acquiring = False


class DemoPointDetectorChannelDevice(Device):
    """Demo tango counting device."""

    channel: device_property = device_property(dtype=int, default_value=0)

    green_mode = GreenMode.Asyncio
    _value = 0
    _locator_x = ""
    _locator_y = ""
    _elapsed = 0.0
    _dp_x: Device | None = None
    _dp_y = None
    _mode: Mode = Mode.LOW
    _energy_modes = [10, 100]

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
    async def locator_x(self):
        return self._locator_x

    async def write_locator_x(self, value: str):
        self._locator_x = value

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
    async def locator_y(self):
        return self._locator_y

    async def write_locator_y(self, value: str):
        self._locator_y = value

    @attribute(dtype=Mode, access=AttrWriteType.READ_WRITE)
    async def mode(self):
        return self._mode

    async def write_mode(self, value: Mode):
        self._mode = value

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    async def elapsed(self):
        return self._elapsed

    async def write_elapsed(self, value: float):
        self._elapsed = value
        x: float = await self._dp_x.readback  # type: ignore
        y: float = await self._dp_y.readback  # type: ignore
        self._value = math.floor(
            (
                math.sin(x) ** self.channel  # type: ignore
                + math.cos(x * y + self._energy_modes[self._mode])
                + 2
            )
            * 2500
            * self._elapsed
        )  # type: ignore

    @command
    async def connect_devices(self):
        # Connect by tango device proxy to the X motor
        self._dp_x = await DeviceProxy(self._locator_x)  # type: ignore
        # Connect by tango device proxy to the Y motor
        self._dp_y = await DeviceProxy(self._locator_y)  # type: ignore

    @attribute(dtype=int, access=AttrWriteType.READ)
    async def value(self):
        return self._value
