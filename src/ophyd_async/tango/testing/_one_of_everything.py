import numpy as np

from ophyd_async.core import (
    DTypeScalar_co,
    StrictEnum,
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


_dtypes = {
    "str": "DevString",
    "bool": "DevBoolean",
    "enum": "DevEnum",
    "strenum": "DevEnum",
    "int8": "DevShort",
    "uint8": "DevUChar",
    "int16": "DevShort",
    "uint16": "DevUShort",
    "int32": "DevLong",
    "uint32": "DevULong",
    "int64": "DevLong64",
    "uint64": "DevULong64",
    "float32": "DevFloat",
    "float64": "DevDouble",
    "my_state": "DevState",
}

_initial_values = {
    AttrDataFormat.SCALAR: {
        "str": "test_string",
        "bool": True,
        "strenum": 1,  # Tango devices must use ints for enums
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
        "my_state": DevState.INIT,
    },
    AttrDataFormat.SPECTRUM: {
        "str": ["one", "two", "three"],
        "bool": [False, True],
        "strenum": [0, 1, 2],  # Tango devices must use ints for enums
        "int8": int_array_value(np.int8),
        "uint8": int_array_value(np.uint8),
        "int16": int_array_value(np.int16),
        "uint16": int_array_value(np.uint16),
        "int32": int_array_value(np.int32),
        "uint32": int_array_value(np.uint32),
        "int64": int_array_value(np.int64),
        "uint64": int_array_value(np.uint64),
        "float32": float_array_value(np.float32),
        "float64": float_array_value(np.float64),
        "my_state": np.array(
            [DevState.INIT, DevState.ON, DevState.MOVING], dtype=DevState
        ),
    },
    AttrDataFormat.IMAGE: {
        "str": np.array([["one", "two", "three"], ["one", "two", "three"]]),
        "bool": np.array([[False, True], [False, True]]),
        "strenum": np.array(
            [[0, 1, 2], [0, 1, 2]]
        ),  # Tango devices must use ints for enums
        "int8": int_image_value(np.int8),
        "uint8": int_image_value(np.uint8),
        "int16": int_image_value(np.int16),
        "uint16": int_image_value(np.uint16),
        "int32": int_image_value(np.int32),
        "uint32": int_image_value(np.uint32),
        "int64": int_image_value(np.int64),
        "uint64": int_image_value(np.uint64),
        "float32": float_image_value(np.float32),
        "float64": float_image_value(np.float64),
        "my_state": np.array(
            [
                [DevState.INIT, DevState.ON, DevState.MOVING],
                [DevState.INIT, DevState.ON, DevState.MOVING],
            ],
            dtype=DevState,
        ),
    },
}


class OneOfEverythingTangoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        for dformat, initial_values in _initial_values.items():
            if dformat == AttrDataFormat.SPECTRUM:
                suffix = "_spectrum"
            elif dformat == AttrDataFormat.IMAGE:
                suffix = "_image"
            else:
                suffix = ""  # scalar
            for prefix, value in initial_values.items():
                name = prefix + suffix
                self.attr_values[name] = value
                if prefix == "strenum":
                    labels = [e.value for e in ExampleStrEnum]
                else:
                    labels = []
                attr = attribute(
                    name=name,
                    dtype=_dtypes[prefix],
                    dformat=dformat,
                    access=AttrWriteType.READ_WRITE,
                    fget=self.read,
                    fset=self.write,
                    max_dim_x=100,
                    max_dim_y=2,
                    enum_labels=labels,
                )
                self.add_attribute(attr)
                self.set_change_event(name, True, False)

    @command
    def reset_values(self):
        for name, value in _initial_values[AttrDataFormat.SCALAR].items():
            self.attr_values[name] = value
        for name, value in _initial_values[AttrDataFormat.SPECTRUM].items():
            self.attr_values[name + "_spectrum"] = value
        for name, value in _initial_values[AttrDataFormat.IMAGE].items():
            self.attr_values[name + "_image"] = value

    def read(self, attr):
        value = self.attr_values[attr.get_name()]
        attr.set_value(value)  # fails with enums

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)
