from collections.abc import Generator

import numpy as np
import pytest

from ophyd_async.tango.core import TangoReadable
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
)
from ophyd_async.testing import assert_reading, assert_value
from tango import DeviceProxy, DevState
from tango.test_context import MultiDeviceTestContext


@pytest.fixture(scope="module")  # module level scope doesn't work properly...
def ophyd_and_tango_device() -> Generator[tuple[TangoReadable, DeviceProxy]]:
    with MultiDeviceTestContext(
        [
            {
                "class": OneOfEverythingTangoDevice,
                "devices": [{"name": "everything/device/1"}],
            }
        ],
        process=True,
    ) as context:
        yield (
            TangoReadable(context.get_device_access("everything/device/1")),
            context.get_device("everything/device/1"),
        )


@pytest.fixture
async def everything_device(ophyd_and_tango_device) -> TangoReadable:
    ophyd_device, tango_device = ophyd_and_tango_device
    tango_device.reset_values()
    return ophyd_device


_scalar_vals = {
    "str": "test_string",
    "bool": True,
    "strenum": ExampleStrEnum.B,
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
}
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
    "strenum": np.array(
        [ExampleStrEnum.A.value, ExampleStrEnum.B.value, ExampleStrEnum.C.value],
        dtype=str,
    ),
    "str": ["one", "two", "three"],
    "bool": np.array([False, True]),
    "my_state": np.array(
        [DevState.INIT, DevState.ON, DevState.MOVING]
    ),  # fails if we specify dtype
}

_image_vals = {k: np.vstack((v, v)) for k, v in _array_vals.items()}


async def assert_val_reading(signal, value, name=""):
    await assert_value(signal, value)
    await assert_reading(signal, {name: {"value": value}})


async def test_set_with_converter(everything_device):
    await everything_device.connect()
    with pytest.raises(TypeError):
        await everything_device.strenum.set(0)
    with pytest.raises(ValueError):
        await everything_device.strenum.set("NON_ENUM_VALUE")
    await everything_device.strenum.set("AAA")
    await everything_device.strenum.set(ExampleStrEnum.B)
    await everything_device.strenum.set(ExampleStrEnum.C.value)

    # setting enum spectrum works with lists and arrays
    await everything_device.strenum_spectrum.set(["AAA", "BBB"])
    await everything_device.strenum_spectrum.set(np.array(["BBB", "CCC"]))
    await everything_device.strenum_spectrum.set(
        [
            ExampleStrEnum.B,
            ExampleStrEnum.C,
        ]
    )
    await everything_device.strenum_spectrum.set(
        np.array(
            [
                ExampleStrEnum.A,
                ExampleStrEnum.B,
            ],
            dtype=ExampleStrEnum,  # doesn't work when dtype is str
        )
    )

    await everything_device.strenum_image.set([["AAA", "BBB"], ["AAA", "BBB"]])
    await everything_device.strenum_image.set(
        np.array([["AAA", "BBB"], ["AAA", "BBB"]])
    )
    await everything_device.strenum_image.set(
        [
            [
                ExampleStrEnum.B,
                ExampleStrEnum.C,
            ],
            [
                ExampleStrEnum.B,
                ExampleStrEnum.C,
            ],
        ]
    )
    await everything_device.strenum_image.set(
        np.array(
            [
                [
                    ExampleStrEnum.B,
                    ExampleStrEnum.C,
                ],
                [
                    ExampleStrEnum.B,
                    ExampleStrEnum.C,
                ],
            ],
            dtype=ExampleStrEnum,
        )
    )


async def test_assert_val_reading_everything_tango(everything_device):
    await everything_device.connect()
    await assert_val_reading(everything_device.str, _scalar_vals["str"])
    await assert_val_reading(everything_device.bool, _scalar_vals["bool"])
    await assert_val_reading(everything_device.strenum, _scalar_vals["strenum"])
    await assert_val_reading(everything_device.int8, _scalar_vals["int8"])
    await assert_val_reading(everything_device.uint8, _scalar_vals["uint8"])
    await assert_val_reading(everything_device.int16, _scalar_vals["int16"])
    await assert_val_reading(everything_device.uint16, _scalar_vals["uint16"])
    await assert_val_reading(everything_device.int32, _scalar_vals["int32"])
    await assert_val_reading(everything_device.uint32, _scalar_vals["uint32"])
    await assert_val_reading(everything_device.int64, _scalar_vals["int64"])
    await assert_val_reading(everything_device.uint64, _scalar_vals["uint64"])
    await assert_val_reading(everything_device.float32, _scalar_vals["float32"])
    await assert_val_reading(everything_device.float64, _scalar_vals["float64"])
    await assert_val_reading(everything_device.my_state, _scalar_vals["my_state"])

    await assert_val_reading(everything_device.str_spectrum, _array_vals["str"])
    await assert_val_reading(everything_device.bool_spectrum, _array_vals["bool"])
    await assert_val_reading(everything_device.strenum_spectrum, _array_vals["strenum"])
    await assert_val_reading(everything_device.int8_spectrum, _array_vals["int8"])
    await assert_val_reading(everything_device.uint8_spectrum, _array_vals["uint8"])
    await assert_val_reading(everything_device.int16_spectrum, _array_vals["int16"])
    await assert_val_reading(everything_device.uint16_spectrum, _array_vals["uint16"])
    await assert_val_reading(everything_device.int32_spectrum, _array_vals["int32"])
    await assert_val_reading(everything_device.uint32_spectrum, _array_vals["uint32"])
    await assert_val_reading(everything_device.int64_spectrum, _array_vals["int64"])
    await assert_val_reading(everything_device.uint64_spectrum, _array_vals["uint64"])
    await assert_val_reading(everything_device.float32_spectrum, _array_vals["float32"])
    await assert_val_reading(everything_device.float64_spectrum, _array_vals["float64"])
    await assert_val_reading(
        everything_device.my_state_spectrum, _array_vals["my_state"]
    )

    await assert_val_reading(everything_device.str_image, _image_vals["str"])
    await assert_val_reading(everything_device.bool_image, _image_vals["bool"])
    await assert_val_reading(everything_device.strenum_image, _image_vals["strenum"])
    await assert_val_reading(everything_device.int8_image, _image_vals["int8"])
    await assert_val_reading(everything_device.uint8_image, _image_vals["uint8"])
    await assert_val_reading(everything_device.int16_image, _image_vals["int16"])
    await assert_val_reading(everything_device.uint16_image, _image_vals["uint16"])
    await assert_val_reading(everything_device.int32_image, _image_vals["int32"])
    await assert_val_reading(everything_device.uint32_image, _image_vals["uint32"])
    await assert_val_reading(everything_device.int64_image, _image_vals["int64"])
    await assert_val_reading(everything_device.uint64_image, _image_vals["uint64"])
    await assert_val_reading(everything_device.float32_image, _image_vals["float32"])
    await assert_val_reading(everything_device.float64_image, _image_vals["float64"])
    await assert_val_reading(everything_device.my_state_image, _image_vals["my_state"])
