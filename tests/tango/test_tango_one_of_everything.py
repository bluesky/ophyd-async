import numpy as np
import pytest

from ophyd_async.tango.core import TangoReadable
from ophyd_async.tango.testing._one_of_everything import (
    ExampleIntEnum,
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
)
from ophyd_async.testing import (
    assert_value,
)
from tango.test_context import MultiDeviceTestContext


@pytest.fixture(scope="module")  # module level scope doesn't work properly...
def everything_tango_device():
    with MultiDeviceTestContext(
        [
            {
                "class": OneOfEverythingTangoDevice,
                "devices": [{"name": "everything/device/1"}],
            }
        ],
        process=True,
    ) as context:
        yield TangoReadable(context.get_device_access("everything/device/1"))


_array_vals = {
    "int8": np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
    "uint8": np.array([0, 255, 0, 1, 2, 3, 4], dtype=np.uint8),
    "int16": np.array([-32768, 32767, 0, 1, 2, 3, 4], dtype=np.int16),
    "uint16": np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
    "int32": np.array([-2147483648, 2147483647, 0, 1, 2, 3, 4], dtype=np.int32),
    "uint32": np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
    "int64": np.array(
        [-9223372036854775808, 9223372036854775807, 0, 1, 2, 3, 4],
        dtype=np.int64,
    ),
    "uint64": np.array([0, 18446744073709551615, 0, 1, 2, 3, 4], dtype=np.uint64),
    "float32": np.array(
        [
            -3.4028235e38,
            3.4028235e38,
            1.1754944e-38,
            1.4012985e-45,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=np.float32,
    ),
    "float64": np.array(
        [
            -1.79769313e308,
            1.79769313e308,
            2.22507386e-308,
            4.94065646e-324,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=np.float64,
    ),
    "enum": [ExampleIntEnum.A, ExampleIntEnum.C],
    "strenum": [ExampleStrEnum.A, ExampleStrEnum.B, ExampleStrEnum.C],
}

_image_vals = {k: np.vstack((v, v)) for k, v in _array_vals.items()}


async def test_assert_with_enums(everything_tango_device):
    # currently broken
    await everything_tango_device.connect()
    await assert_value(everything_tango_device.strenum, ExampleStrEnum.B)
    await assert_value(everything_tango_device.strenum_spectrum, _array_vals["stenum"])
    await assert_value(everything_tango_device.strenum_image, _image_vals["strenum"])


async def test_assert_value_everything_tango(everything_tango_device):
    await everything_tango_device.connect()
    await assert_value(everything_tango_device.str, "test_string")
    await assert_value(everything_tango_device.bool, True)
    await assert_value(everything_tango_device.enum, ExampleIntEnum.B)
    await assert_value(everything_tango_device.int8, 1)
    await assert_value(everything_tango_device.uint8, 1)
    await assert_value(everything_tango_device.int16, 1)
    await assert_value(everything_tango_device.uint16, 1)
    await assert_value(everything_tango_device.int32, 1)
    await assert_value(everything_tango_device.uint32, 1)
    await assert_value(everything_tango_device.int64, 1)
    await assert_value(everything_tango_device.uint64, 1)
    await assert_value(everything_tango_device.float32, 1.234)
    await assert_value(everything_tango_device.float64, 1.234)

    await assert_value(everything_tango_device.enum_spectrum, _array_vals["enum"])
    await assert_value(everything_tango_device.int8_spectrum, _array_vals["int8"])
    await assert_value(everything_tango_device.uint8_spectrum, _array_vals["uint8"])
    await assert_value(everything_tango_device.int16_spectrum, _array_vals["int16"])
    await assert_value(everything_tango_device.uint16_spectrum, _array_vals["uint16"])
    await assert_value(everything_tango_device.int32_spectrum, _array_vals["int32"])
    await assert_value(everything_tango_device.uint32_spectrum, _array_vals["uint32"])
    await assert_value(everything_tango_device.int64_spectrum, _array_vals["int64"])
    await assert_value(everything_tango_device.uint64_spectrum, _array_vals["uint64"])
    await assert_value(everything_tango_device.float32_spectrum, _array_vals["float32"])
    await assert_value(everything_tango_device.float64_spectrum, _array_vals["float64"])

    await assert_value(everything_tango_device.enum_image, _image_vals["enum"])
    await assert_value(everything_tango_device.str_spectrum, ["one", "two", "three"])
    await assert_value(everything_tango_device.int8_image, _image_vals["int8"])
    await assert_value(everything_tango_device.uint8_image, _image_vals["uint8"])
    await assert_value(everything_tango_device.int16_image, _image_vals["int16"])
    await assert_value(everything_tango_device.uint16_image, _image_vals["uint16"])
    await assert_value(everything_tango_device.int32_image, _image_vals["int32"])
    await assert_value(everything_tango_device.uint32_image, _image_vals["uint32"])
    await assert_value(everything_tango_device.int64_image, _image_vals["int64"])
    await assert_value(everything_tango_device.uint64_image, _image_vals["uint64"])
    await assert_value(everything_tango_device.float32_image, _image_vals["float32"])
    await assert_value(everything_tango_device.float64_image, _image_vals["float64"])


# TODO: test int and str enums
