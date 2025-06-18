import textwrap
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import numpy as np
from tango import AttrDataFormat, AttrWriteType, DevState
from tango.server import Device, attribute, command

from ophyd_async.core import (
    Array1D,
    DTypeScalar_co,
    StrictEnum,
)
from ophyd_async.testing import float_array_value, int_array_value

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


def _valid_command(dformat: AttrDataFormat, dtype: str):
    if dtype == "DevUChar":
        return False
    if dformat != AttrDataFormat.SCALAR and dtype in ["DevState", "DevEnum"]:
        return False
    return True


@dataclass
class AttributeData(Generic[T]):
    name: str
    tango_type: str
    initial_scalar: T
    initial_spectrum: Array1D


_all_attribute_definitions = [
    AttributeData(
        "str",
        "DevString",
        "test_string",
        np.array(["one", "two", "three"], dtype=str),
    ),
    AttributeData(
        "bool",
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
        np.array([DevState.INIT, DevState.ON, DevState.MOVING], dtype=DevState),
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

    def add_array_attrs(self, name: str, dtype: str, initial_value: np.ndarray):
        spectrum_name = f"{name}_spectrum"
        spectrum_attr = attribute(
            name=spectrum_name,
            dtype=dtype,
            dformat=AttrDataFormat.SPECTRUM,
            access=AttrWriteType.READ_WRITE,
            fget=self.read,
            fset=self.write,
            max_dim_x=initial_value.shape[-1],
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
            max_dim_x=initial_value.shape[-1],
            max_dim_y=2,
            enum_labels=[e.value for e in ExampleStrEnum],
        )
        self._add_attr(spectrum_attr, initial_value)
        # have image just be 2 of the initial spectrum stacked
        self._add_attr(image_attr, np.vstack((initial_value, initial_value)))

    def add_scalar_command(self, name: str, dtype: str):
        if _valid_command(AttrDataFormat.SCALAR, dtype):
            self.add_command(
                command(
                    f=getattr(self, f"{name}_cmd"),
                    dtype_in=dtype,
                    dtype_out=dtype,
                    dformat_in=AttrDataFormat.SCALAR,
                    dformat_out=AttrDataFormat.SCALAR,
                ),
            )

    def add_spectrum_command(self, name: str, dtype: str):
        if _valid_command(AttrDataFormat.SPECTRUM, dtype):
            self.add_command(
                command(
                    f=getattr(self, f"{name}_spectrum_cmd"),
                    dtype_in=dtype,
                    dtype_out=dtype,
                    dformat_in=AttrDataFormat.SPECTRUM,
                    dformat_out=AttrDataFormat.SPECTRUM,
                ),
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

    echo_command_code = textwrap.dedent(
        """\
            def {}(self, arg):
                return arg
            """
    )

    for attr_data in _all_attribute_definitions:
        if _valid_command(AttrDataFormat.SCALAR, attr_data.tango_type):
            exec(echo_command_code.format(f"{attr_data.name}_cmd"))
        if _valid_command(AttrDataFormat.SPECTRUM, attr_data.tango_type):
            exec(echo_command_code.format(f"{attr_data.name}_spectrum_cmd"))
