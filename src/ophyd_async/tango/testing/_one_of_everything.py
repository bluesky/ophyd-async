import textwrap
from dataclasses import dataclass
from random import choice
from typing import Any, Generic, TypeVar

import numpy as np

from ophyd_async.core import (
    Array1D,
    DTypeScalar_co,
    StrictEnum,
)
from ophyd_async.tango.core import DevStateEnum
from ophyd_async.testing import float_array_value, int_array_value
from tango import AttrDataFormat, AttrWriteType, DevState
from tango.server import Device, attribute, command

T = TypeVar("T")


class ExampleStrEnum(StrictEnum):
    A = "AAA"
    B = "BBB"
    C = "CCC"


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


@dataclass
class AttributeData(Generic[T]):
    name: str
    tango_type: str
    py_type: type
    initial_value: T
    random_put_values: tuple[T, ...]
    dformat = AttrDataFormat.SCALAR
    cmd_name: str | None

    def random_value(self):
        return choice(self.random_put_values)


class SpectrumData(AttributeData):
    dformat = AttrDataFormat.SPECTRUM

    def random_value(self):
        array = self.initial_value.copy()
        for idx in range(len(array)):
            array[idx] = choice(self.random_put_values)
        return array


class ImageData(AttributeData):
    dformat = AttrDataFormat.IMAGE
    cmd_name = None

    def random_value(self):
        array = self.initial_value.copy()
        for idx in range(array.shape[1]):
            array[0, idx] = choice(self.random_put_values)
            array[1, idx] = choice(self.random_put_values)
        return array


everything_signal_info = []


def add_ads(
    name: str,
    tango_type: str,
    py_type: type,
    initial_scalar,
    initial_spectrum,
    choices,
):
    scalar_cmd = f"{name}_cmd" if tango_type != "DevUChar" else None
    everything_signal_info.append(
        AttributeData(name, tango_type, py_type, initial_scalar, choices, scalar_cmd)
    )
    spectrum_cmd = (
        f"{name}_spectrum_cmd"
        if tango_type not in ["DevUChar", "DevState", "DevEnum"]
        else None
    )
    everything_signal_info.append(
        SpectrumData(
            f"{name}_spectrum",
            tango_type,
            Array1D[py_type],
            initial_spectrum,
            choices,
            spectrum_cmd,
        )
    )
    everything_signal_info.append(
        ImageData(
            f"{name}_image",
            tango_type,
            np.ndarray[Any, np.dtype[py_type]],
            np.vstack((initial_spectrum, initial_spectrum)),
            choices,
            None,
        )
    )


add_ads(
    "str",
    "DevString",
    str,
    "test_string",
    np.array(["one", "two", "three"], dtype=str),
    ("four", "five", "six"),
)
add_ads(
    "bool",
    "DevBoolean",
    bool,
    True,
    np.array([False, True], dtype=bool),
    (False, True),
)
add_ads("strenum", "DevEnum", StrictEnum, 1, np.array([0, 1, 2]), (0, 1, 2))
add_ads("int8", "DevShort", int, 1, int_array_value(np.int8), (1, 2, 3, 4, 5))
add_ads("uint8", "DevUChar", int, 1, int_array_value(np.uint8), (1, 2, 3, 4, 5))
add_ads("int16", "DevShort", int, 1, int_array_value(np.int16), (1, 2, 3, 4, 5))
add_ads("uint16", "DevUShort", int, 1, int_array_value(np.uint16), (1, 2, 3, 4, 5))
add_ads("int32", "DevLong", int, 1, int_array_value(np.int32), (1, 2, 3, 4, 5))
add_ads("uint32", "DevULong", int, 1, int_array_value(np.uint32), (1, 2, 3, 4, 5))
add_ads("int64", "DevLong64", int, 1, int_array_value(np.int64), (1, 2, 3, 4, 5))
add_ads("uint64", "DevULong64", int, 1, int_array_value(np.uint64), (1, 2, 3, 4, 5))
add_ads(
    "float32",
    "DevFloat",
    float,
    1.234,
    float_array_value(np.float32),
    (1.234, 2.345, 3.456),
)
add_ads(
    "float64",
    "DevDouble",
    float,
    1.234,
    float_array_value(np.float64),
    (1.234, 2.345, 3.456),
)
add_ads(
    "my_state",
    "DevState",
    DevStateEnum,
    DevState.INIT,
    np.array([DevState.INIT, DevState.ON, DevState.MOVING], dtype=DevState),
    (DevState.INIT, DevState.ON, DevState.MOVING),
)


class OneOfEverythingTangoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        self.reset_values()
        for attr_data in everything_signal_info:
            attr = attribute(
                name=attr_data.name,
                dtype=attr_data.tango_type,
                dformat=attr_data.dformat,
                access=AttrWriteType.READ_WRITE,
                fget=self.read,
                fset=self.write,
                max_dim_x=0
                if attr_data.dformat == AttrDataFormat.SCALAR
                else attr_data.initial_value.shape[-1],
                max_dim_y=2,
                enum_labels=[e.value for e in ExampleStrEnum],
            )
            self.add_attribute(attr)
            self.set_change_event(attr.name, True, False)
            if attr_data.cmd_name:
                self.add_command(
                    command(
                        f=getattr(self, attr_data.cmd_name),
                        dtype_in=attr_data.tango_type,
                        dtype_out=attr_data.tango_type,
                        dformat_in=attr_data.dformat,
                        dformat_out=attr_data.dformat,
                    )
                )

    @command
    def reset_values(self):
        for attr_data in everything_signal_info:
            self.attr_values[attr_data.name] = attr_data.initial_value

    def read(self, attr):
        value = self.attr_values[attr.get_name()]
        attr.set_value(value)

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)

    echo_command_code = textwrap.dedent(
        """\
            def {}(self, arg):
                return arg
            """
    )

    for attr_data in everything_signal_info:
        if attr_data.dformat != AttrDataFormat.IMAGE:
            exec(echo_command_code.format(f"{attr_data.name}_cmd"))
