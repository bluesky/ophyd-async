from enum import Enum, IntEnum

import numpy as np

from ophyd_async.core import (
    Array1D,
    DTypeScalar_co,
    StrictEnum,
)
from tango import AttrDataFormat, AttrWriteType
from tango.server import Device, attribute


class ExampleStrEnum(StrictEnum):
    A = "AAA"
    B = "BBB"
    C = "CCC"


def int_spectrum_value(
    dtype: type[DTypeScalar_co],
) -> Array1D[DTypeScalar_co]:  # import from .testing?
    iinfo = np.iinfo(dtype)  # type: ignore
    return np.array([iinfo.min, iinfo.max, 0, 1, 2, 3, 4], dtype=dtype)


def int_image_value(
    dtype: type[DTypeScalar_co],
):
    # how do we type this?
    array_1d = int_spectrum_value(dtype)
    return np.vstack((array_1d, array_1d))


def float_spectrum_value(dtype: type[DTypeScalar_co]) -> Array1D[DTypeScalar_co]:
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


def float_image_value(
    dtype: type[DTypeScalar_co],
):
    # how do we type this?
    array_1d = float_spectrum_value(dtype)
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
    },
    AttrDataFormat.SPECTRUM: {
        "str": ["one", "two", "three"],
        "bool": [False, True],
        "strenum": [0, 1, 2],  # Tango devices must use ints for enums
        "int8": int_spectrum_value(np.int8),
        "uint8": int_spectrum_value(np.uint8),
        "int16": int_spectrum_value(np.int16),
        "uint16": int_spectrum_value(np.uint16),
        "int32": int_spectrum_value(np.int32),
        "uint32": int_spectrum_value(np.uint32),
        "int64": int_spectrum_value(np.int64),
        "uint64": int_spectrum_value(np.uint64),
        "float32": float_spectrum_value(np.float32),
        "float64": float_spectrum_value(np.float64),
    },
    AttrDataFormat.IMAGE: {
        # "str": # TODO
        # "bool": # TODO
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

    def read(self, attr):
        value = self.attr_values[attr.get_name()]
        attr.set_value(value)  # fails with enums

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)
