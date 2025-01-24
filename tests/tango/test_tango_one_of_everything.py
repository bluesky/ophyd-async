from collections.abc import Sequence
from enum import IntEnum

import numpy as np
import pytest

from ophyd_async.tango.core import TangoReadable
from ophyd_async.testing import (
    ExampleEnum,
    assert_value,
)
from ophyd_async.testing._one_of_everything import (
    EverythingSignal,
    get_every_signal_data,
)
from tango import AttrDataFormat, AttrWriteType
from tango.server import Device, attribute
from tango.test_context import MultiDeviceTestContext

dtypes = {
    "int": "DevShort",
    "float": "DevDouble",
    "str": "DevString",
    "bool": "DevBoolean",
    "enum": "DevEnum",
    "int8a": "DevShort",
    "uint8a": "DevUChar",
    "int16a": "DevShort",
    "uint16a": "DevUShort",
    "int32a": "DevLong",
    "uint32a": "DevULong",
    "int64a": "DevLong64",
    "uint64a": "DevULong64",
    "float32a": "DevFloat",
    "float64a": "DevDouble",
    "stra": "DevString",
    "enuma": "DevEnum",
    # TODO fix ndarray: have to explicitly provide dtype when defining initial value
    # "ndarray": "DevLong",
    "intenum": "DevEnum",
    "intenuma": "DevEnum",
}


class ExampleIntEnum(IntEnum):
    # we can't use StrictEnums...
    ZERO = 0
    ONE = 1
    TWO = 2


class EverythingTangoDevice(Device):
    attr_values = {}

    def initialize_dynamic_attributes(self):
        for data in get_every_signal_data() + [
            EverythingSignal("intenum", ExampleIntEnum, ExampleIntEnum.ONE),
            EverythingSignal(
                "intenuma",
                Sequence[ExampleIntEnum],
                [ExampleIntEnum.ONE, ExampleIntEnum.TWO],
            ),
        ]:
            if data.name.endswith("a"):  # array
                d_format = AttrDataFormat.SPECTRUM
            else:
                d_format = AttrDataFormat.SCALAR
            # TODO: we should have IMAGE types too...

            if data.name not in dtypes:
                print("skipping", data.name, "for now")
                continue
            self.attr_values[data.name] = data.initial_value
            attr = attribute(
                name=data.name,
                dtype=dtypes[data.name],
                dformat=d_format,
                access=AttrWriteType.READ_WRITE,
                fget=self.read,
                fset=self.write,
                max_dim_x=100,
                max_dim_y=2,
                enum_labels=[member.name for member in ExampleEnum],
            )
            self.add_attribute(attr)
            self.set_change_event(data.name, True, False)

    def read(self, attr):
        value = self.attr_values[attr.get_name()]
        attr.set_value(value)  # fails with enums...

    def write(self, attr):
        new_value = attr.get_write_value()
        self.attr_values[attr.get_name()] = new_value
        self.push_change_event(attr.get_name(), new_value)


@pytest.fixture(scope="module")  # module level scope doesn't work properly...
def everything_tango_device():
    with MultiDeviceTestContext(
        [
            {
                "class": EverythingTangoDevice,
                "devices": [{"name": "everything/device/1"}],
            }
        ],
        process=True,
    ) as context:
        yield context.get_device_access("everything/device/1")


_array_vals = {
    "int8a": np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
    "uint8a": np.array([0, 255, 0, 1, 2, 3, 4], dtype=np.uint8),
    "int16a": np.array([-32768, 32767, 0, 1, 2, 3, 4], dtype=np.int16),
    "uint16a": np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
    "int32a": np.array([-2147483648, 2147483647, 0, 1, 2, 3, 4], dtype=np.int32),
    "uint32a": np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
    "int64a": np.array(
        [-9223372036854775808, 9223372036854775807, 0, 1, 2, 3, 4],
        dtype=np.int64,
    ),
    "uint64a": np.array([0, 18446744073709551615, 0, 1, 2, 3, 4], dtype=np.uint64),
    "float32a": np.array(
        [
            -3.4028235e38,
            3.4028235e38,
            1.1754944e-38,
            1.4012985e-45,
            0.0000000e00,
            1.2340000e00,
            2.3400000e05,
            3.4499999e-06,
        ],
        dtype=np.float32,
    ),
    "float64a": np.array(
        [
            -1.79769313e308,
            1.79769313e308,
            2.22507386e-308,
            4.94065646e-324,
            0.00000000e000,
            1.23400000e000,
            2.34000000e005,
            3.45000000e-006,
        ],
        dtype=np.float64,
    ),
}


async def test_assert_value_everything_tango(everything_tango_device):
    one_of_everything_device = TangoReadable(everything_tango_device)
    await one_of_everything_device.connect()
    await assert_value(one_of_everything_device.int, 1)
    await assert_value(one_of_everything_device.float, 1.234)
    await assert_value(one_of_everything_device.str, "test_string")
    await assert_value(one_of_everything_device.bool, True)
    await assert_value(one_of_everything_device.int8a, _array_vals["int8a"])
    await assert_value(one_of_everything_device.uint8a, _array_vals["uint8a"])
    await assert_value(one_of_everything_device.int16a, _array_vals["int16a"])
    await assert_value(one_of_everything_device.uint16a, _array_vals["uint16a"])
    await assert_value(one_of_everything_device.int32a, _array_vals["int32a"])
    await assert_value(one_of_everything_device.uint32a, _array_vals["uint32a"])
    await assert_value(one_of_everything_device.int64a, _array_vals["int64a"])
    await assert_value(one_of_everything_device.uint64a, _array_vals["uint64a"])
    await assert_value(one_of_everything_device.float32a, _array_vals["float32a"])
    await assert_value(one_of_everything_device.float64a, _array_vals["float64a"])
    await assert_value(one_of_everything_device.stra, ["one", "two", "three"])
    await assert_value(one_of_everything_device.intenum, ExampleIntEnum.ONE)
    await assert_value(
        one_of_everything_device.intenuma, [ExampleIntEnum.ONE, ExampleIntEnum.TWO]
    )


#    await assert_value(
#        one_of_everything_device.ndarray, np.array(([1, 2, 3], [4, 5, 6]),
#        dtype=np.int32)
#    )
