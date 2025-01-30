import numpy as np
import pytest

from ophyd_async.tango.core import TangoReadable
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
)
from ophyd_async.testing import assert_reading, assert_value
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
    "strenum": np.array(
        [ExampleStrEnum.A.value, ExampleStrEnum.B.value, ExampleStrEnum.C.value],
        dtype=str,
    ),
    "str": ["one", "two", "three"],
    "bool": np.array([False, True]),
}

_image_vals = {k: np.vstack((v, v)) for k, v in _array_vals.items()}


async def test_set_with_converter(everything_tango_device):
    await everything_tango_device.connect()
    with pytest.raises(TypeError):
        await everything_tango_device.strenum.set(0)
    with pytest.raises(ValueError):
        await everything_tango_device.strenum.set("NON_ENUM_VALUE")
    await everything_tango_device.strenum.set("AAA")
    await everything_tango_device.strenum.set(ExampleStrEnum.B)
    await everything_tango_device.strenum.set(ExampleStrEnum.C.value)

    # setting enum spectrum works with lists and arrays
    await everything_tango_device.strenum_spectrum.set(["AAA", "BBB"])
    await everything_tango_device.strenum_spectrum.set(np.array(["BBB", "CCC"]))
    await everything_tango_device.strenum_spectrum.set(
        [
            ExampleStrEnum.B,
            ExampleStrEnum.C,
        ]
    )
    await everything_tango_device.strenum_spectrum.set(
        np.array(
            [
                ExampleStrEnum.A,
                ExampleStrEnum.B,
            ],
            dtype=ExampleStrEnum,  # doesn't work when dtype is str
        )
    )

    await everything_tango_device.strenum_image.set([["AAA", "BBB"], ["AAA", "BBB"]])
    await everything_tango_device.strenum_image.set(
        np.array([["AAA", "BBB"], ["AAA", "BBB"]])
    )
    await everything_tango_device.strenum_image.set(
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
    await everything_tango_device.strenum_image.set(
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


async def test_assert_value_everything_tango(everything_tango_device):
    await everything_tango_device.connect()
    await assert_value(everything_tango_device.str, "test_string")
    await assert_value(everything_tango_device.bool, True)
    await assert_value(everything_tango_device.strenum, ExampleStrEnum.B)
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

    await assert_value(everything_tango_device.str_spectrum, _array_vals["str"])
    await assert_value(everything_tango_device.bool_spectrum, _array_vals["bool"])
    await assert_value(everything_tango_device.strenum_spectrum, _array_vals["strenum"])
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

    await assert_value(everything_tango_device.str_image, _image_vals["str"])
    await assert_value(everything_tango_device.bool_image, _image_vals["bool"])
    await assert_value(everything_tango_device.strenum_image, _image_vals["strenum"])
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


async def test_assert_reading_everything_tango(everything_tango_device):
    await everything_tango_device.connect()

    await assert_reading(everything_tango_device.str, {"": {"value": "test_string"}})
    await assert_reading(everything_tango_device.bool, {"": {"value": True}})
    await assert_reading(
        everything_tango_device.strenum, {"": {"value": ExampleStrEnum.B}}
    )
    await assert_reading(everything_tango_device.int8, {"": {"value": 1}})
    await assert_reading(everything_tango_device.uint8, {"": {"value": 1}})
    await assert_reading(everything_tango_device.int16, {"": {"value": 1}})
    await assert_reading(everything_tango_device.uint16, {"": {"value": 1}})
    await assert_reading(everything_tango_device.int32, {"": {"value": 1}})
    await assert_reading(everything_tango_device.uint32, {"": {"value": 1}})
    await assert_reading(everything_tango_device.int64, {"": {"value": 1}})
    await assert_reading(everything_tango_device.uint64, {"": {"value": 1}})
    await assert_reading(everything_tango_device.float32, {"": {"value": 1.234}})
    await assert_reading(everything_tango_device.float64, {"": {"value": 1.234}})

    await assert_reading(
        everything_tango_device.str_spectrum, {"": {"value": _array_vals["str"]}}
    )
    await assert_reading(
        everything_tango_device.bool_spectrum, {"": {"value": _array_vals["bool"]}}
    )
    await assert_reading(
        everything_tango_device.strenum_spectrum,
        {"": {"value": _array_vals["strenum"]}},
    )
    await assert_reading(
        everything_tango_device.int8_spectrum, {"": {"value": _array_vals["int8"]}}
    )
    await assert_reading(
        everything_tango_device.uint8_spectrum, {"": {"value": _array_vals["uint8"]}}
    )
    await assert_reading(
        everything_tango_device.int16_spectrum, {"": {"value": _array_vals["int16"]}}
    )
    await assert_reading(
        everything_tango_device.uint16_spectrum, {"": {"value": _array_vals["uint16"]}}
    )
    await assert_reading(
        everything_tango_device.int32_spectrum, {"": {"value": _array_vals["int32"]}}
    )
    await assert_reading(
        everything_tango_device.uint32_spectrum, {"": {"value": _array_vals["uint32"]}}
    )
    await assert_reading(
        everything_tango_device.int64_spectrum, {"": {"value": _array_vals["int64"]}}
    )
    await assert_reading(
        everything_tango_device.uint64_spectrum, {"": {"value": _array_vals["uint64"]}}
    )
    await assert_reading(
        everything_tango_device.float32_spectrum,
        {"": {"value": _array_vals["float32"]}},
    )
    await assert_reading(
        everything_tango_device.float64_spectrum,
        {"": {"value": _array_vals["float64"]}},
    )

    await assert_reading(
        everything_tango_device.str_image, {"": {"value": _image_vals["str"]}}
    )
    await assert_reading(
        everything_tango_device.bool_image, {"": {"value": _image_vals["bool"]}}
    )
    await assert_reading(
        everything_tango_device.strenum_image, {"": {"value": _image_vals["strenum"]}}
    )
    await assert_reading(
        everything_tango_device.int8_image, {"": {"value": _image_vals["int8"]}}
    )
    await assert_reading(
        everything_tango_device.uint8_image, {"": {"value": _image_vals["uint8"]}}
    )
    await assert_reading(
        everything_tango_device.int16_image, {"": {"value": _image_vals["int16"]}}
    )
    await assert_reading(
        everything_tango_device.uint16_image, {"": {"value": _image_vals["uint16"]}}
    )
    await assert_reading(
        everything_tango_device.int32_image, {"": {"value": _image_vals["int32"]}}
    )
    await assert_reading(
        everything_tango_device.uint32_image, {"": {"value": _image_vals["uint32"]}}
    )
    await assert_reading(
        everything_tango_device.int64_image, {"": {"value": _image_vals["int64"]}}
    )
    await assert_reading(
        everything_tango_device.uint64_image, {"": {"value": _image_vals["uint64"]}}
    )
    await assert_reading(
        everything_tango_device.float32_image, {"": {"value": _image_vals["float32"]}}
    )
    await assert_reading(
        everything_tango_device.float64_image, {"": {"value": _image_vals["float64"]}}
    )
