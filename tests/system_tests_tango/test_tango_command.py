from collections.abc import Sequence

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    Command,
    NotConnectedError,
    StandardReadable,
    TriggerableCommand,
)
from ophyd_async.tango.core import (
    DevStateEnum,
    TangoDevice,
    TangoDoubleStringTable,
    TangoLongStringTable,
    tango_command,
    tango_triggerable_command,
)
from ophyd_async.tango.testing import (
    ExampleStrEnum,
    OneOfEverythingTangoDevice,
    TangoSubprocessDeviceServer,
)

TEST_PARAMS = [
    (None, None, "void_cmd"),
    (bool, True, "a_bool_cmd"),
    (int, 42, "int32_cmd"),
    (float, 3.14, "float64_cmd"),
    (str, "hello", "a_str_cmd"),
    (ExampleStrEnum, ExampleStrEnum.A, "strenum_cmd"),
    (DevStateEnum, DevStateEnum.ON, "my_state_cmd"),
    (Array1D[np.bool_], np.array([True, False], dtype=np.bool_), "a_bool_spectrum_cmd"),
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
    (Sequence[str], ["a", "b"], "a_str_spectrum_cmd"),
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
def everything_device_trl():
    with TangoSubprocessDeviceServer(
        [{"class": OneOfEverythingTangoDevice, "devices": [{"name": "test/device/2"}]}]
    ) as context:
        yield context.trls["test/device/2"]


class TangoEverythingOphydDevice(TangoDevice, StandardReadable):
    # datatype of enum commands must be explicitly hinted
    strenum_cmd: Command[[ExampleStrEnum], ExampleStrEnum]
    a_bool_cmd: Command[[bool], bool]
    float32_spectrum_cmd: Command[[Array1D[np.float32]], Array1D[np.float32]]


class TangoEverythingOphydDeviceTriggerableAnnotation(TangoDevice, StandardReadable):
    void_cmd: TriggerableCommand


@pytest.fixture()
async def everything_device(everything_device_trl):
    return TangoEverythingOphydDevice(everything_device_trl, name="everything_device")


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
    for name in ["strenum_cmd", "a_bool_cmd", "float32_spectrum_cmd"]:
        assert hasattr(everything_device, name)
    await everything_device.connect()

    for ctype, val, name in TEST_PARAMS:
        cmd = getattr(everything_device, name)
        if name == "void_cmd":
            assert isinstance(cmd, TriggerableCommand)
        else:
            assert isinstance(cmd, Command)
        if name in ["int8_spectrum_cmd", "uint8_spectrum_cmd"]:
            assert Array1D[np.uint8] == cmd.signature.return_annotation
            assert (
                Array1D[np.uint8]
                == list(cmd.signature.parameters.values())[0].annotation
            )
        else:
            assert ctype == cmd.signature.return_annotation
            print(name, cmd.signature)
            if name == "void_cmd":
                assert not list(cmd.signature.parameters.values())
            else:
                assert ctype == list(cmd.signature.parameters.values())[0].annotation

        if isinstance(val, np.ndarray):
            assert np.array_equal(val, await cmd.execute(val))
        else:
            assert val == await cmd.execute(val)


@pytest.mark.parametrize("ctype, val, name", TEST_PARAMS)
@pytest.mark.asyncio
async def test_tango_command_factory(
    everything_device_trl: str,
    ctype,
    val,
    name,
):
    # Determine expected datatype and triggerable status based on name
    if name == "void_cmd":
        expected_datatype = None
    elif name in ["int8_spectrum_cmd", "uint8_spectrum_cmd"]:
        expected_datatype = Array1D[np.uint8]
    else:
        expected_datatype = ctype

    trl = ""

    def spec(x: ctype) -> ctype: ...

    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + f"/{name}" + everything_device_trl[-9:]

    if ctype == Array1D[np.int8]:
        with pytest.raises(TypeError) as excinfo:
            tango_command(call_spec=spec, trl=trl, device_proxy=None, name=name)
        assert "Arrays of type np.int8 are not supported" in str(excinfo.value)
        return
    elif ctype is None:
        cmd = tango_triggerable_command(
            trl=trl,
            device_proxy=None,
            name=name,
        )
    else:
        cmd = tango_command(call_spec=spec, trl=trl, device_proxy=None, name=name)

    if name == "void_cmd":
        assert isinstance(cmd, TriggerableCommand)
    else:
        assert isinstance(cmd, Command)

    await cmd.connect()

    if name == "void_cmd":
        assert cmd.signature is None
    else:
        assert expected_datatype == cmd.signature.return_annotation

    if isinstance(val, np.ndarray):
        assert np.array_equal(val, await cmd.execute(val))
    else:
        assert val == await cmd.execute(val)


@pytest.mark.asyncio
async def test_tango_command_validation(
    everything_device_trl: str,
):
    # This should pass
    def call_spec(x: float) -> float: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + "/float64_cmd" + everything_device_trl[-9:]
    cmd = tango_command(call_spec=call_spec, trl=trl, name="float64_cmd")
    await cmd.connect()
    ret = await cmd.execute(1.0)
    assert ret == 1.0

    # This should pass
    def call_spec(x: float) -> None: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + "/float64_cmd" + everything_device_trl[-9:]
    cmd = tango_command(call_spec=call_spec, trl=trl, name="float64_cmd")
    await cmd.connect()
    ret = await cmd.execute(1.0)
    assert ret == 1.0

    # Multiple input params should fail
    # Commands with more than one input parameter are not yet supported.
    def call_spec(x: float, y: int) -> float: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + "/float64_cmd" + everything_device_trl[-9:]
    with pytest.raises(TypeError) as excinfo:
        tango_command(call_spec=call_spec, trl=trl, name="float64_cmd")
    assert "Commands with more than one input parameter" in str(excinfo.value)

    # Mistyped return type should fail unless it is None
    def call_spec(x: float) -> int: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + "/float64_cmd" + everything_device_trl[-9:]
    cmd = tango_command(call_spec=call_spec, trl=trl, name="float64_cmd")
    with pytest.raises(TypeError) as excinfo:
        await cmd.connect()
    assert "not <class 'int'>" in str(excinfo.value)

    # Mistyped input parameter should fail unless it is None
    def call_spec(x: Array1D[np.float32]) -> float: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = everything_device_trl[:-9] + "/float64_cmd" + everything_device_trl[-9:]
    cmd = tango_command(call_spec=call_spec, trl=trl, name="float64_cmd")
    with pytest.raises(TypeError) as excinfo:
        await cmd.connect()
    assert "has input parameter of type <class 'float'>, not" in str(excinfo.value)


class TangoEverythingOphydDeviceWithBadAnnotation(TangoDevice, StandardReadable):
    # datatype of enum commands must be explicitly hinted
    strenum_cmd: Command[[ExampleStrEnum], ExampleStrEnum]
    a_bool_cmd: Command[[bool], None]
    float32_spectrum_cmd: Command[[Array1D[np.float32]], Array1D[np.float32]]


@pytest.fixture()
async def everything_device_bad_anno(everything_device_trl):
    return TangoEverythingOphydDeviceWithBadAnnotation(everything_device_trl)


@pytest.fixture()
async def everything_device_triggerable(everything_device_trl):
    return TangoEverythingOphydDeviceTriggerableAnnotation(
        everything_device_trl, auto_fill_signals=False
    )


@pytest.mark.asyncio
async def test_tango_command_bad_annotation(
    everything_device_bad_anno,
):
    with pytest.raises(NotConnectedError) as excinfo:
        await everything_device_bad_anno.connect()
    assert "not <class 'NoneType'>" in str(excinfo.value)


@pytest.mark.asyncio
async def test_triggerable_command_annotation(everything_device_triggerable):
    attr = everything_device_triggerable.void_cmd
    assert isinstance(attr, TriggerableCommand)
    await everything_device_triggerable.connect()
    await attr.trigger()


@pytest.mark.asyncio
async def test_tango_command_mixed_types(everything_device_trl: str):
    """Test Command[[float], bool] with different input and output types."""

    def call_spec(x: float) -> bool: ...

    trl = ""
    if everything_device_trl.endswith("#dbase=no"):
        trl = (
            everything_device_trl[:-9]
            + "/float_to_bool_cmd"
            + everything_device_trl[-9:]
        )
    cmd = tango_command(call_spec=call_spec, trl=trl, name="float_to_bool_cmd")
    await cmd.connect()
    assert cmd.signature.return_annotation is bool
    assert list(cmd.signature.parameters.values())[0].annotation is float
    assert await cmd.execute(1.0) is True
    assert await cmd.execute(-1.0) is False
