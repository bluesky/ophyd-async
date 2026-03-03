import pytest
from typing import Annotated as A
import numpy as np
from collections.abc import Sequence
from ophyd_async.core import (
    Array1D,
    Command,
    DeviceMock,
    NotConnectedError,
    SoftCommandBackend,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    make_converter,
    soft_command,
    SignalRW,
    SignalR,
    StandardReadable,
    StandardReadableFormat as Format,
)
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
)
from ophyd_async.tango.core import TangoDevice, get_full_attr_trl, DevStateEnum

class MyStrictEnum(StrictEnum):
    A = "A"
    B = "B"


class MySubsetEnum(SubsetEnum):
    X = "X"
    Y = "Y"


class MySupersetEnum(SupersetEnum):
    P = "P"
    Q = "Q"


class MyTable(Table):
    a: Array1D[np.int32]
    b: Sequence[str]


TEST_PARAMS = [
    (bool, True, "bool_cmd"),
    (int, 42, "int32_cmd"),
    (float, 3.14, "float64_cmd"),
    (str, "hello", "str_cmd"),
    (MyStrictEnum, MyStrictEnum.A, "strenum_cmd"),
    (MySubsetEnum, MySubsetEnum.X, "strenum_cmd"),
    (MySupersetEnum, MySupersetEnum.P, "strenum_cmd"),
    (Array1D[np.bool_], np.array([True, False], dtype=np.bool_), "bool_spectrum_cmd"),
    (Array1D[np.int8], np.array([1, 2], dtype=np.int8), "int8_spectrum_cmd"),
    (Array1D[np.int16], np.array([1, 2], dtype=np.int16), "int16_spectrum_cmd"),
    (Array1D[np.uint16], np.array([1, 2], dtype=np.uint16), "uint16_spectrum_cmd"),
    (Array1D[np.int32], np.array([1, 2], dtype=np.int32), "int32_spectrum_cmd"),
    (Array1D[np.uint32], np.array([1, 2], dtype=np.uint32), "uint32_spectrum_cmd"),
    (Array1D[np.int64], np.array([1, 2], dtype=np.int64), "int64_spectrum_cmd"),
    (Array1D[np.uint64], np.array([1, 2], dtype=np.uint64), "uint64_spectrum_cmd"),
    (Array1D[np.float32], np.array([1.1, 2.2], dtype=np.float32), "float32_spectrum_cmd"),
    (Array1D[np.float64], np.array([1.1, 2.2], dtype=np.float64), "float64_spectrum_cmd"),
    (Sequence[str], ["a", "b"], "str_spectrum_cmd"),
    (Sequence[MyStrictEnum], [MyStrictEnum.A, MyStrictEnum.B], "strenum_cmd"),
    (Sequence[MySubsetEnum], [MySubsetEnum.X, MySubsetEnum.Y], "strenum_cmd"),
    (Sequence[MySupersetEnum], [MySupersetEnum.P, MySupersetEnum.Q], "strenum_cmd"),
    # TODO: Add Table case (DEV_LONGSTRINGARRAY and DEV_DOUBLESTRINGARRAY)
    # (MyTable, MyTable(a=np.array([1], dtype=np.int32), b=["hi"]), ""),  # No exact match
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
    strenum_cmd: A[Command[ExampleStrEnum, ExampleStrEnum], Format.HINTED_UNCACHED_SIGNAL]


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
    cmd = getattr(everything_device, "bool_cmd")
    assert isinstance(cmd, Command)
    assert bool == cmd._connector.backend.get_return_type()
