from collections.abc import Sequence

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    Command,
    StandardReadable,
)
from ophyd_async.tango.core import (
    DevStateEnum,
    TangoDevice,
    TangoDoubleStringTable,
    TangoLongStringTable,
)
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
)

TEST_PARAMS = [
    (bool, True, "bool_cmd"),
    (int, 42, "int32_cmd"),
    (float, 3.14, "float64_cmd"),
    (str, "hello", "str_cmd"),
    (ExampleStrEnum, ExampleStrEnum.A, "strenum_cmd"),
    (DevStateEnum, DevStateEnum.ON, "my_state_cmd"),
    (Array1D[np.bool_], np.array([True, False], dtype=np.bool_), "bool_spectrum_cmd"),
    (Array1D[np.int8], np.array([1, 2], dtype=np.int8), "int8_spectrum_cmd"),
    (Array1D[np.uint8], np.array([1, 2], dtype=np.uint8), "uint8_spectrum_cmd"),
    (Array1D[np.int16], np.array([1, 2], dtype=np.int16), "int16_spectrum_cmd"),
    (Array1D[np.uint16], np.array([1, 2], dtype=np.uint16), "uint16_spectrum_cmd"),
    (Array1D[np.int32], np.array([1, 2], dtype=np.int32), "int32_spectrum_cmd"),
    (Array1D[np.uint32], np.array([1, 2], dtype=np.uint32), "uint32_spectrum_cmd"),
    (Array1D[np.int64], np.array([1, 2], dtype=np.int64), "int64_spectrum_cmd"),
    (Array1D[np.uint64], np.array([1, 2], dtype=np.uint64), "uint64_spectrum_cmd"),
    (
        Array1D[np.float32],
        np.array([1.1, 2.2], dtype=np.float32),
        "float32_spectrum_cmd",
    ),
    (
        Array1D[np.float64],
        np.array([1.1, 2.2], dtype=np.float64),
        "float64_spectrum_cmd",
    ),
    (Sequence[str], ["a", "b"], "str_spectrum_cmd"),
    (
        TangoLongStringTable,
        TangoLongStringTable(long=[1, 2], string=["a", "b"]),
        "long_string_cmd",
    ),
    (
        TangoDoubleStringTable,
        TangoDoubleStringTable(double=[1.1, 2.2], string=["a", "b"]),
        "double_string_cmd",
    ),
]


# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def everything_device_trl(subprocess_helper):
    with subprocess_helper(
        [{"class": OneOfEverythingTangoDevice, "devices": [{"name": "test/device/2"}]}]
    ) as context:
        yield context.trls["test/device/2"]


class TangoEverythingOphydDevice(TangoDevice, StandardReadable):
    # datatype of enum commands must be explicitly hinted
    strenum_cmd: Command[[ExampleStrEnum], ExampleStrEnum]
    bool_cmd: Command[[bool], bool]
    float32_spectrum_cmd: Command[[Array1D[np.float32]], Array1D[np.float32]]


@pytest.fixture()
async def everything_device(everything_device_trl):
    return TangoEverythingOphydDevice(everything_device_trl)


@pytest.mark.asyncio
async def test_tango_command_connect(everything_device: TangoDevice):
    await everything_device.connect()
    cmd_names = [param[2] for param in TEST_PARAMS]
    for name in cmd_names:
        assert name in dir(everything_device)


@pytest.mark.asyncio
async def test_tango_command(
    everything_device: TangoDevice,
    everything_signal_info,
):
    await everything_device.connect()

    for ctype, val, name in TEST_PARAMS:
        cmd = getattr(everything_device, name)
        assert isinstance(cmd, Command)
        if name in ["int8_spectrum_cmd", "uint8_spectrum_cmd"]:
            assert Array1D[np.uint8] == cmd._connector.backend.get_return_type()
        else:
            assert ctype == cmd._connector.backend.get_return_type()
        if isinstance(val, np.ndarray):
            assert np.array_equal(val, await cmd.execute(val))
        else:
            assert val == await cmd.execute(val)
