import textwrap
from dataclasses import dataclass
from random import choice
from typing import Generic

import numpy as np

from ophyd_async.core import (
    Array1D,
    DTypeScalar_co,
    StrictEnum,
    T,
)
from ophyd_async.testing import float_array_value, int_array_value
from tango import AttrDataFormat, AttrWriteType, DevState
from tango.server import Device, attribute, command


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
    type_name: str
    tango_type: str
    dtype: type
    initial_scalar: T
    initial_spectrum: Array1D[T]  # type: ignore
    random_put_values: tuple[T, ...]

    @property
    def initial_image(self):
        # return a (2, N) np array with two of the initial spectrum values stacked
        return np.vstack((self.initial_spectrum, self.initial_spectrum))

    @property
    def spectrum_name(self) -> str:
        return f"{self.type_name}_spectrum"

    @property
    def image_name(self) -> str:
        return f"{self.type_name}_image"

    @property
    def random_scalar(self) -> T:
        return self.dtype(choice(self.random_put_values))

    @property
    def random_spectrum(self) -> Array1D[T]:
        array = self.initial_spectrum.copy()
        for idx in range(len(array)):
            array[idx] = self.random_scalar
        return array  # pretty ugly

    @property
    def random_image(self):  # how to type this?
        array_1d = self.random_spectrum
        return np.vstack((array_1d, array_1d))


attribute_datas = [
    AttributeData(
        "str",
        "DevString",
        str,
        "test_string",
        np.array(["one", "two", "three"], dtype=str),
        ("four", "five", "six"),
    ),
    AttributeData(
        "bool",
        "DevBoolean",
        bool,
        True,
        np.array([False, True], dtype=bool),
        (False, True),
    ),
    AttributeData(
        "strenum", "DevEnum", int, 1, np.array([0, 1, 2]), (0, 1, 2)
    ),  # right dtype?
    AttributeData(
        "int8", "DevShort", int, 1, int_array_value(np.int8), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "uint8", "DevUChar", int, 1, int_array_value(np.uint8), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "int16", "DevShort", int, 1, int_array_value(np.int16), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "uint16", "DevUShort", int, 1, int_array_value(np.uint16), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "int32", "DevLong", int, 1, int_array_value(np.int32), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "uint32", "DevULong", int, 1, int_array_value(np.uint32), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "int64", "DevLong64", int, 1, int_array_value(np.int64), (1, 2, 3, 4, 5)
    ),
    AttributeData(
        "uint64",
        "DevULong64",
        int,
        1,
        int_array_value(np.uint64),
        (1, 2, 3, 4, 5),
    ),
    AttributeData(
        "float32",
        "DevFloat",
        float,
        1.234,
        float_array_value(np.float32),
        (1.234, 2.345, 3.456),
    ),
    AttributeData(
        "float64",
        "DevDouble",
        float,
        1.234,
        float_array_value(np.float64),
        (1.234, 2.345, 3.456),
    ),
    AttributeData(
        "my_state",
        "DevState",
        DevState,
        DevState.INIT,
        np.array([DevState.INIT, DevState.ON, DevState.MOVING], dtype=DevState),
        (DevState.INIT, DevState.ON, DevState.MOVING),
    ),
]


class OneOfEverythingTangoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        attr_args = {
            "access": AttrWriteType.READ_WRITE,
            "fget": self.read,
            "fset": self.write,
            "max_dim_x": 100,
            "max_dim_y": 2,
            "enum_labels": [e.value for e in ExampleStrEnum],
        }
        self.reset_values()
        for attr_data in attribute_datas:
            attr_args["dtype"] = attr_data.tango_type
            scalar_attr = attribute(
                name=attr_data.type_name, dformat=AttrDataFormat.SCALAR, **attr_args
            )
            spectrum_attr = attribute(
                name=attr_data.spectrum_name,
                dformat=AttrDataFormat.SPECTRUM,
                **attr_args,
            )
            image_attr = attribute(
                name=attr_data.image_name, dformat=AttrDataFormat.IMAGE, **attr_args
            )
            for attr in (scalar_attr, spectrum_attr, image_attr):
                self.add_attribute(attr)
                self.set_change_event(attr.name, True, False)

            if attr_data.tango_type == "DevUChar":
                continue
            self.add_command(
                command(
                    f=getattr(self, f"{attr_data.type_name}_cmd"),
                    dtype_in=attr_data.tango_type,
                    dtype_out=attr_data.tango_type,
                    dformat_in=AttrDataFormat.SCALAR,
                    dformat_out=AttrDataFormat.SCALAR,
                )
            )
            if attr_data.tango_type in ["DevState", "DevEnum"]:
                continue
            self.add_command(
                command(
                    f=getattr(self, f"{attr_data.type_name}_spectrum_cmd"),
                    dtype_in=attr_data.tango_type,
                    dtype_out=attr_data.tango_type,
                    dformat_in=AttrDataFormat.SPECTRUM,
                    dformat_out=AttrDataFormat.SPECTRUM,
                )
            )

    @command
    def reset_values(self):
        for attr_data in attribute_datas:
            self.attr_values[attr_data.type_name] = attr_data.initial_scalar
            self.attr_values[attr_data.type_name + "_spectrum"] = (
                attr_data.initial_spectrum
            )
            self.attr_values[attr_data.type_name + "_image"] = attr_data.initial_image

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

    for attr_data in attribute_datas:
        exec(echo_command_code.format(f"{attr_data.type_name}_cmd"))
        exec(echo_command_code.format(f"{attr_data.type_name}_spectrum_cmd"))
